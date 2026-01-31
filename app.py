"""
================================================================================
SUPPLY CHAIN SHORTAGE KPI WEB DASHBOARD
================================================================================
Browser-based intranet application for monitoring picking shortages.
Run with: python app.py
Access at: http://localhost:5000 or http://<your-ip>:5000
================================================================================
"""

from flask import Flask, render_template_string, jsonify, request, Response
import pymysql
from datetime import datetime
from collections import defaultdict
import csv
import io

app = Flask(__name__)

# Database connection
def get_connection():
    return pymysql.connect(
        host='451-srv-fbwl01',
        port=3306,
        user='ReadUser',
        password='Metrohm2026!',
        database='MetrohmSpectro'
    )

def get_current_shortages():
    """Get current shortage breakdown with categorization"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        pi.id as pickitem_id,
        pi.qty as qty_short,
        p.id as part_id,
        p.num as part_num,
        p.description,
        p.defaultBomId as has_bom,
        pk.id as pick_id,
        COALESCE(ot.name, 'N/A') as order_type,
        (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         WHERE t.partId = p.id AND t.qty > 0 
         AND l.countedAsAvailable = 1) as available_qoh,
        (SELECT COALESCE(SUM(t.qtyCommitted), 0) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         WHERE t.partId = p.id AND t.qty > 0 
         AND l.countedAsAvailable = 1) as committed_qty,
        (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         WHERE t.partId = p.id AND t.qty > 0 
         AND LOWER(l.name) LIKE '%wip%') as wip_qty,
        (SELECT COALESCE(SUM(poi.qtyToFulfill - poi.qtyFulfilled), 0) 
         FROM poitem poi 
         JOIN po ON poi.poId = po.id 
         WHERE poi.partId = p.id 
         AND po.statusId IN (20, 30, 40)) as on_order_qty,
        (SELECT COALESCE(SUM(moitem.qtyToFulfill - moitem.qtyFulfilled), 0)
         FROM moitem
         JOIN mo ON moitem.moId = mo.id
         WHERE moitem.partId = p.id
         AND moitem.typeId = 10
         AND mo.statusId IN (10, 20, 50)
         AND moitem.statusId NOT IN (50, 60, 70)) as being_manufactured_qty,
        -- Get related SO number and customer
        (SELECT so.num FROM soitem si JOIN so ON si.soId = so.id WHERE si.id = pi.soItemId) as so_num,
        (SELECT so.customerId FROM soitem si JOIN so ON si.soId = so.id WHERE si.id = pi.soItemId) as so_customer_id,
        (SELECT c.name FROM soitem si JOIN so ON si.soId = so.id JOIN customer c ON so.customerId = c.id WHERE si.id = pi.soItemId) as so_customer_name,
        -- Get related WO number (from pick's woItemId)
        (SELECT wo.num FROM woitem wi JOIN wo ON wi.woId = wo.id WHERE wi.id = pi.woItemId) as wo_num,
        -- Get related MO number (via WO -> moitem -> mo)
        (SELECT mo.num FROM woitem wi 
         JOIN moitem mi ON wi.moItemId = mi.id 
         JOIN mo ON mi.moId = mo.id 
         WHERE wi.id = pi.woItemId) as mo_num,
        -- When pick has SO but no WO link, derive WO/MO from same SO and part (open MO)
        (SELECT wo.num FROM soitem si JOIN so ON so.id = si.soId JOIN mo ON mo.soId = so.id AND mo.statusId IN (10,20,50) JOIN moitem mi ON mi.moId = mo.id AND mi.partId = p.id AND mi.typeId = 10 JOIN wo ON wo.moItemId = mi.id WHERE si.id = pi.soItemId AND pi.woItemId IS NULL LIMIT 1) as wo_num_derived,
        (SELECT mo.num FROM soitem si JOIN so ON so.id = si.soId JOIN mo ON mo.soId = so.id AND mo.statusId IN (10,20,50) JOIN moitem mi ON mi.moId = mo.id AND mi.partId = p.id AND mi.typeId = 10 WHERE si.id = pi.soItemId AND pi.woItemId IS NULL LIMIT 1) as mo_num_derived,
        -- Get PO numbers for this part
        (SELECT GROUP_CONCAT(DISTINCT po.num ORDER BY poi.dateScheduledFulfillment SEPARATOR ', ')
         FROM poitem poi 
         JOIN po ON poi.poId = po.id 
         WHERE poi.partId = p.id 
         AND po.statusId IN (20, 30, 40)) as po_nums,
        -- Get earliest PO scheduled fulfillment date
        (SELECT MIN(poi.dateScheduledFulfillment)
         FROM poitem poi 
         JOIN po ON poi.poId = po.id 
         WHERE poi.partId = p.id 
         AND po.statusId IN (20, 30, 40)) as po_date_scheduled,
        -- Check if there's ANY open MO for this part (as finished good)
        (SELECT COUNT(DISTINCT mo.id)
         FROM mo
         JOIN moitem mofg ON mofg.moId = mo.id
         WHERE mofg.partId = p.id
         AND mofg.typeId = 10  -- Finished good
         AND mo.statusId IN (10, 20, 50)  -- Open MO statuses
         AND mofg.statusId NOT IN (50, 60, 70)  -- Not completed
        ) as has_open_mo,
        -- Check if this part is listed as a raw material (ADD) in any open MO
        (SELECT COUNT(DISTINCT mo.id)
         FROM mo
         JOIN moitem mi ON mi.moId = mo.id
         WHERE mi.partId = p.id
         AND mi.typeId = 20  -- Raw material (ADD)
         AND mo.statusId IN (10, 20, 50)  -- Open MO statuses
         AND mi.statusId NOT IN (50, 60, 70)  -- Not completed
        ) as is_raw_material_in_mo,
        -- Check if there's an open MO for this part (as finished good) with raw material shortages
        (SELECT COUNT(DISTINCT mo.id)
         FROM mo
         JOIN moitem mofg ON mofg.moId = mo.id
         WHERE mofg.partId = p.id
         AND mofg.typeId = 10  -- Finished good
         AND mo.statusId IN (10, 20, 50)  -- Open MO statuses
         AND mofg.statusId NOT IN (50, 60, 70)  -- Not completed
         AND EXISTS (
             -- Check if this MO has raw material shortages
             SELECT 1
             FROM moitem mi
             JOIN part prm ON mi.partId = prm.id
             WHERE mi.moId = mo.id
             AND mi.typeId = 20  -- Raw material
             AND mi.statusId NOT IN (50, 60, 70)  -- Not completed
             AND (
                 -- Check if raw material has no available stock
                 (SELECT COALESCE(SUM(t.qty - t.qtyCommitted), 0)
                  FROM tag t
                  JOIN location l ON t.locationId = l.id
                  WHERE t.partId = prm.id
                  AND t.qty > 0
                  AND l.countedAsAvailable = 1) <= 0
                 -- And not being manufactured
                 AND NOT EXISTS (
                     SELECT 1
                     FROM moitem mi2
                     JOIN mo mo2 ON mi2.moId = mo2.id
                     WHERE mi2.partId = prm.id
                     AND mi2.typeId = 10
                     AND mo2.statusId IN (10, 20, 50)
                     AND mi2.statusId NOT IN (50, 60, 70)
                 )
             )
         )) as mo_with_rm_shortage
    FROM pickitem pi
    JOIN pickitemstatus pis ON pi.statusId = pis.id
    JOIN part p ON pi.partId = p.id
    JOIN pick pk ON pi.pickId = pk.id
    LEFT JOIN ordertype ot ON pi.orderTypeId = ot.id
    WHERE pis.id = 5
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return results

def categorize_shortages(shortages, filter_customer_id=None, exclude_mode=False):
    """Categorize shortages into TRUE vs WIP
    
    Args:
        shortages: List of shortage records
        filter_customer_id: Optional customer ID to filter TRUE shortages (e.g., 14 for B&W TEK SHANGHAI)
        exclude_mode: If True, exclude the customer; if False, include only that customer
    """
    true_shortages = []
    wip_shortages = []
    other_shortages = []
    
    for row in shortages:
        pickitem_id, qty_short, part_id, part_num, desc, has_bom, pick_id, order_type, available_qoh, committed_qty, wip_qty, on_order, being_mfg_qty, so_num, so_customer_id, so_customer_name, wo_num, mo_num, wo_num_derived, mo_num_derived, po_nums, po_date_scheduled, has_open_mo, is_raw_material_in_mo, mo_with_rm_shortage = row
        total_wip = float(wip_qty) + float(being_mfg_qty)
        net_available = float(available_qoh) - float(committed_qty)
        # A part is manufactured if it has a BOM (defaultBomId is not NULL and > 0)
        is_manufactured = has_bom is not None and int(has_bom or 0) > 0
        has_open_mo_count = int(has_open_mo or 0)
        is_raw_material_in_mo_count = int(is_raw_material_in_mo or 0)
        mo_with_rm_shortage_count = int(mo_with_rm_shortage or 0)
        # Use derived WO/MO when pick has SO but no direct woItemId link
        wo_display = wo_num or wo_num_derived
        mo_display = mo_num or mo_num_derived
        
        # Build order reference: show SO, WO, and MO when available (so WIP shows WO/MO, not only SO)
        orders = []
        if so_num:
            orders.append(f"SO:{so_num}")
        if wo_display:
            orders.append(f"WO:{wo_display}")
        if mo_display:
            orders.append(f"MO:{mo_display}")
        order_ref = ", ".join(orders) if orders else order_type
        
        # Format PO scheduled date
        po_date_str = ''
        if po_date_scheduled:
            if hasattr(po_date_scheduled, 'strftime'):
                po_date_str = po_date_scheduled.strftime('%Y-%m-%d')
            else:
                po_date_str = str(po_date_scheduled)[:10]
        
        item = {
            'pickitem_id': pickitem_id,
            'part_id': part_id,
            'part_num': part_num,
            'description': desc or '',
            'pick_id': pick_id,
            'order_type': order_type,
            'order_ref': order_ref,
            'qty_short': float(qty_short),
            'so_num': so_num or '',
            'so_customer_id': so_customer_id,
            'so_customer_name': so_customer_name or '',
            'wo_num': wo_num or '',
            'mo_num': mo_num or '',
            'po_nums': po_nums or '',
            'po_date_scheduled': po_date_str,
            'available_qty': float(available_qoh),
            'committed_qty': float(committed_qty),
            'net_available_qty': net_available,
            'wip_qty': float(wip_qty),
            'being_mfg_qty': float(being_mfg_qty),
            'on_order_qty': float(on_order),
            'is_manufactured': is_manufactured,
            'has_open_mo': has_open_mo_count,
            'is_raw_material_in_mo': is_raw_material_in_mo_count,
            'mo_with_rm_shortage': mo_with_rm_shortage_count
        }
        
        # Categorize based on Fishbowl's logic:
        # - "ADD" in MO = TRUE Material Shortage (part is raw material, needs to be purchased/added)
        # - "Create" in MO = WIP Shortage (part is finished good, needs MO to be created)
        # - Purchased parts (no BOM) with no stock = TRUE Material Shortage
        
        # Check if part is listed as raw material (ADD) in any open MO
        is_add_in_mo = is_raw_material_in_mo_count > 0
        
        # Determine if it's a supply chain shortage (TRUE Material Shortage)
        is_supply_chain_shortage = False
        if is_add_in_mo:
            # Part is listed as raw material (ADD) in an open MO → TRUE shortage
            is_supply_chain_shortage = True
        elif is_manufactured:
            # Manufactured part: Only a supply chain shortage if MO exists with raw material shortages
            is_supply_chain_shortage = mo_with_rm_shortage_count > 0
        else:
            # Purchased part: Supply chain shortage if no net available stock
            is_supply_chain_shortage = net_available <= 0
        
        # Apply categorization
        if is_supply_chain_shortage:
            # TRUE shortage: Supply chain shortage (needs materials to be purchased/added)
            # - Part is raw material (ADD) in open MO
            # - Purchased part with no stock
            # - Manufactured part with MO that has raw material shortages
            # Apply customer filter if specified
            if filter_customer_id is None:
                # No filter - include all
                true_shortages.append(item)
            elif exclude_mode:
                # Exclude mode - include if NOT this customer (or no customer)
                if item['so_customer_id'] is None or item['so_customer_id'] != filter_customer_id:
                    true_shortages.append(item)
            else:
                # Include mode - include only this customer
                if item['so_customer_id'] == filter_customer_id:
                    true_shortages.append(item)
        elif is_manufactured:
            # WIP Shortage: Manufactured part that needs MO to be created or is waiting for manufacturing
            # Conditions for WIP shortage:
            # 1. Part is manufactured (has BOM)
            # 2. Part is NOT listed as raw material (ADD) in any open MO
            # 3. If it has an open MO, that MO does NOT have raw material shortages
            # 4. Needs MO to be created (has_open_mo_count == 0) OR MO is waiting for manufacturing
            wip_shortages.append(item)
        else:
            # Purchased part (no BOM) that is NOT a supply chain shortage
            # This means net_available > 0, so it's a location/commitment/sequencing issue
            other_shortages.append(item)
    
    return true_shortages, wip_shortages, other_shortages

def get_weekly_kpi():
    """Get weekly shortage KPIs - shows currently open shortages from picks created in each week
    
    Note: This shows shortages that are still open today, grouped by the week the pick was created.
    To show historical totals (including resolved shortages), we would need to use audit tables.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        YEAR(pk.dateCreated) as yr,
        WEEK(pk.dateCreated) as wk,
        MIN(DATE(pk.dateCreated)) as week_start,
        COUNT(DISTINCT pi.id) as short_pick_items,
        COUNT(DISTINCT pi.partId) as unique_parts_short,
        COUNT(DISTINCT pk.id) as picks_with_shorts
    FROM pickitem pi
    JOIN pick pk ON pi.pickId = pk.id
    WHERE pi.statusId = 5
    AND pk.dateCreated >= DATE_SUB(CURDATE(), INTERVAL 12 WEEK)
    GROUP BY YEAR(pk.dateCreated), WEEK(pk.dateCreated)
    ORDER BY yr DESC, wk DESC
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{'week_start': str(r[2]), 'short_items': r[3], 'unique_parts': r[4], 'affected_picks': r[5]} for r in results]

def get_weekly_kpi_historical():
    """Get historical weekly shortage KPIs using audit tables - shows all shortages that existed during each week
    
    This includes both resolved and currently open shortages, giving a true historical snapshot.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Find all pickitems that had statusId=5 (shortage) during each week
    # We use the revision timestamp to determine when the shortage occurred
    query = '''
    SELECT 
        YEAR(r.timestamp) as yr,
        WEEK(r.timestamp) as wk,
        MIN(DATE(r.timestamp)) as week_start,
        COUNT(DISTINCT pia.id) as short_pick_items,
        COUNT(DISTINCT pia.partId) as unique_parts_short,
        COUNT(DISTINCT pia.pickId) as picks_with_shorts
    FROM pickitem_aud pia
    JOIN revinfo r ON pia.REV = r.id
    WHERE pia.statusId = 5
    AND r.timestamp >= DATE_SUB(CURDATE(), INTERVAL 12 WEEK)
    GROUP BY YEAR(r.timestamp), WEEK(r.timestamp)
    ORDER BY yr DESC, wk DESC
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{'week_start': str(r[2]), 'short_items': r[3], 'unique_parts': r[4], 'affected_picks': r[5]} for r in results]

def get_monthly_kpi_historical():
    """Get historical monthly shortage KPIs using audit tables - shows all shortages that existed during each month
    
    This includes both resolved and currently open shortages, giving a true historical snapshot.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Find all pickitems that had statusId=5 (shortage) during each month
    # We use the revision timestamp to determine when the shortage occurred
    query = '''
    SELECT 
        YEAR(r.timestamp) as yr,
        MONTH(r.timestamp) as mo,
        CONCAT(YEAR(r.timestamp), '-', LPAD(MONTH(r.timestamp), 2, '0')) as month_label,
        COUNT(DISTINCT pia.id) as short_pick_items,
        COUNT(DISTINCT pia.partId) as unique_parts_short,
        COUNT(DISTINCT pia.pickId) as picks_with_shorts
    FROM pickitem_aud pia
    JOIN revinfo r ON pia.REV = r.id
    WHERE pia.statusId = 5
    AND r.timestamp >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
    GROUP BY YEAR(r.timestamp), MONTH(r.timestamp)
    ORDER BY yr DESC, mo DESC
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{'month': r[2], 'short_items': r[3], 'unique_parts': r[4], 'affected_picks': r[5]} for r in results]

def get_monthly_kpi():
    """Get monthly shortage KPIs"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        YEAR(pk.dateCreated) as yr,
        MONTH(pk.dateCreated) as mo,
        CONCAT(YEAR(pk.dateCreated), '-', LPAD(MONTH(pk.dateCreated), 2, '0')) as month_label,
        COUNT(DISTINCT pi.id) as short_pick_items,
        COUNT(DISTINCT pi.partId) as unique_parts_short,
        COUNT(DISTINCT pk.id) as picks_with_shorts
    FROM pickitem pi
    JOIN pick pk ON pi.pickId = pk.id
    WHERE pi.statusId = 5
    AND pk.dateCreated >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
    GROUP BY YEAR(pk.dateCreated), MONTH(pk.dateCreated)
    ORDER BY yr DESC, mo DESC
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{'month': r[2], 'short_items': r[3], 'unique_parts': r[4], 'affected_picks': r[5]} for r in results]

def get_daily_kpi():
    """Get daily shortage KPIs - shows currently open shortages from picks created each day"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        DATE(pk.dateCreated) as day_date,
        COUNT(DISTINCT pi.id) as short_pick_items,
        COUNT(DISTINCT pi.partId) as unique_parts_short,
        COUNT(DISTINCT pk.id) as picks_with_shorts
    FROM pickitem pi
    JOIN pick pk ON pi.pickId = pk.id
    WHERE pi.statusId = 5
    AND pk.dateCreated >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    GROUP BY DATE(pk.dateCreated)
    ORDER BY day_date DESC
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{'day_date': str(r[0]), 'short_items': r[1], 'unique_parts': r[2], 'affected_picks': r[3]} for r in results]

def get_daily_kpi_historical():
    """Get historical daily shortage KPIs using audit tables - shows all shortages that existed during each day
    
    This includes both resolved and currently open shortages, giving a true historical snapshot.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Find all pickitems that had statusId=5 (shortage) during each day
    # We use the revision timestamp to determine when the shortage occurred
    query = '''
    SELECT 
        DATE(r.timestamp) as day_date,
        COUNT(DISTINCT pia.id) as short_pick_items,
        COUNT(DISTINCT pia.partId) as unique_parts_short,
        COUNT(DISTINCT pia.pickId) as picks_with_shorts
    FROM pickitem_aud pia
    JOIN revinfo r ON pia.REV = r.id
    WHERE pia.statusId = 5
    AND r.timestamp >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    GROUP BY DATE(r.timestamp)
    ORDER BY day_date DESC
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{'day_date': str(r[0]), 'short_items': r[1], 'unique_parts': r[2], 'affected_picks': r[3]} for r in results]

def get_aging():
    """Get aging analysis"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        CASE 
            WHEN DATEDIFF(CURDATE(), pk.dateCreated) <= 7 THEN '0-7 days'
            WHEN DATEDIFF(CURDATE(), pk.dateCreated) <= 14 THEN '8-14 days'
            WHEN DATEDIFF(CURDATE(), pk.dateCreated) <= 30 THEN '15-30 days'
            WHEN DATEDIFF(CURDATE(), pk.dateCreated) <= 60 THEN '31-60 days'
            ELSE '60+ days'
        END as age_bucket,
        COUNT(DISTINCT pi.id) as short_items,
        COUNT(DISTINCT pi.partId) as unique_parts
    FROM pickitem pi
    JOIN pick pk ON pi.pickId = pk.id
    WHERE pi.statusId = 5
    GROUP BY age_bucket
    ORDER BY 
        CASE age_bucket
            WHEN '0-7 days' THEN 1
            WHEN '8-14 days' THEN 2
            WHEN '15-30 days' THEN 3
            WHEN '31-60 days' THEN 4
            ELSE 5
        END
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{'bucket': r[0], 'short_items': r[1], 'unique_parts': r[2]} for r in results]

# ================================================================================
# PURCHASE ORDER MANAGEMENT FUNCTIONS
# ================================================================================

def get_po_summary():
    """Get summary of all purchase orders"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        po.id,
        po.num,
        po.dateCreated,
        po.dateIssued,
        po.dateFirstShip,
        po.dateConfirmed,
        po.dateCompleted,
        v.name as vendor_name,
        v.id as vendor_id,
        pos.name as status,
        po.statusId,
        su.userName as buyer_name,
        po.buyerId,
        (SELECT COUNT(*) FROM poitem poi WHERE poi.poId = po.id) as line_count,
        (SELECT SUM(poi.qtyToFulfill - poi.qtyFulfilled) 
         FROM poitem poi 
         WHERE poi.poId = po.id 
         AND poi.statusId NOT IN (50, 60, 70)) as open_qty,
        (SELECT SUM(poi.totalCost) 
         FROM poitem poi 
         WHERE poi.poId = po.id) as total_cost,
        (SELECT SUM(poi.qtyFulfilled * poi.unitCost) 
         FROM poitem poi 
         WHERE poi.poId = po.id) as fulfilled_cost,
        (SELECT MIN(poi.dateScheduledFulfillment)
         FROM poitem poi
         WHERE poi.poId = po.id
         AND poi.qtyToFulfill > poi.qtyFulfilled) as earliest_scheduled_date
    FROM po
    JOIN vendor v ON po.vendorId = v.id
    JOIN postatus pos ON po.statusId = pos.id
    LEFT JOIN sysuser su ON po.buyerId = su.id
    WHERE po.statusId IN (20, 30, 40)  -- Issued, Picking, Partial
    ORDER BY po.dateCreated DESC
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return results

def get_po_aging():
    """Get PO aging analysis"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        CASE 
            WHEN DATEDIFF(CURDATE(), COALESCE(po.dateIssued, po.dateCreated)) <= 30 THEN '0-30 days'
            WHEN DATEDIFF(CURDATE(), COALESCE(po.dateIssued, po.dateCreated)) <= 60 THEN '31-60 days'
            WHEN DATEDIFF(CURDATE(), COALESCE(po.dateIssued, po.dateCreated)) <= 90 THEN '61-90 days'
            ELSE '90+ days'
        END as age_bucket,
        COUNT(DISTINCT po.id) as po_count,
        SUM((SELECT SUM(poi.totalCost) FROM poitem poi WHERE poi.poId = po.id)) as total_value
    FROM po
    WHERE po.statusId IN (20, 30, 40)
    GROUP BY age_bucket
    ORDER BY 
        CASE age_bucket
            WHEN '0-30 days' THEN 1
            WHEN '31-60 days' THEN 2
            WHEN '61-90 days' THEN 3
            ELSE 4
        END
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{'bucket': r[0], 'po_count': r[1], 'total_value': float(r[2] or 0)} for r in results]

def get_vendor_performance(start_date=None, end_date=None):
    """Get vendor performance metrics with date filtering
    
    Args:
        start_date: Start date for filtering (YYYY-MM-DD format)
        end_date: End date for filtering (YYYY-MM-DD format)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build date filter conditions
    date_filter = ""
    if start_date:
        date_filter += f" AND po.dateIssued >= '{start_date}'"
    if end_date:
        date_filter += f" AND po.dateIssued <= '{end_date}'"
    
    query = f'''
    SELECT 
        v.id,
        v.name as vendor_name,
        COUNT(DISTINCT po.id) as total_pos,
        SUM((SELECT SUM(poi.totalCost) FROM poitem poi WHERE poi.poId = po.id)) as total_value,
        AVG(DATEDIFF(po.dateCompleted, po.dateIssued)) as avg_fulfillment_days,
        COUNT(DISTINCT CASE WHEN po.dateCompleted IS NOT NULL THEN po.id END) as completed_pos,
        -- On-time delivery: POs completed on or before scheduled date
        COUNT(DISTINCT CASE 
            WHEN po.dateCompleted IS NOT NULL 
            AND po.dateCompleted <= COALESCE(
                (SELECT MAX(poi.dateScheduledFulfillment) 
                 FROM poitem poi 
                 WHERE poi.poId = po.id), 
                po.dateIssued
            )
            THEN po.id 
        END) as on_time_pos,
        -- Late deliveries
        COUNT(DISTINCT CASE 
            WHEN po.dateCompleted IS NOT NULL 
            AND po.dateCompleted > COALESCE(
                (SELECT MAX(poi.dateScheduledFulfillment) 
                 FROM poitem poi 
                 WHERE poi.poId = po.id), 
                po.dateIssued
            )
            THEN po.id 
        END) as late_pos,
        -- Average days late (for late deliveries)
        AVG(CASE 
            WHEN po.dateCompleted IS NOT NULL 
            AND po.dateCompleted > COALESCE(
                (SELECT MAX(poi.dateScheduledFulfillment) 
                 FROM poitem poi 
                 WHERE poi.poId = po.id), 
                po.dateIssued
            )
            THEN DATEDIFF(po.dateCompleted, COALESCE(
                (SELECT MAX(poi.dateScheduledFulfillment) 
                 FROM poitem poi 
                 WHERE poi.poId = po.id), 
                po.dateIssued
            ))
            ELSE NULL
        END) as avg_days_late,
        -- Fulfillment rate (completed vs total)
        CASE 
            WHEN COUNT(DISTINCT po.id) > 0 
            THEN (COUNT(DISTINCT CASE WHEN po.dateCompleted IS NOT NULL THEN po.id END) * 100.0 / COUNT(DISTINCT po.id))
            ELSE 0
        END as fulfillment_rate,
        -- On-time delivery rate
        CASE 
            WHEN COUNT(DISTINCT CASE WHEN po.dateCompleted IS NOT NULL THEN po.id END) > 0
            THEN (COUNT(DISTINCT CASE 
                WHEN po.dateCompleted IS NOT NULL 
                AND po.dateCompleted <= COALESCE(
                    (SELECT MAX(poi.dateScheduledFulfillment) 
                     FROM poitem poi 
                     WHERE poi.poId = po.id), 
                    po.dateIssued
                )
                THEN po.id 
            END) * 100.0 / COUNT(DISTINCT CASE WHEN po.dateCompleted IS NOT NULL THEN po.id END))
            ELSE 0
        END as on_time_rate
    FROM po
    JOIN vendor v ON po.vendorId = v.id
    WHERE po.statusId IN (20, 30, 40, 60)  -- Include completed
    AND po.dateIssued IS NOT NULL
    {date_filter}
    GROUP BY v.id, v.name
    HAVING total_pos > 0
    ORDER BY total_value DESC
    LIMIT 50
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{
        'vendor_id': r[0],
        'vendor_name': r[1],
        'total_pos': r[2],
        'total_value': float(r[3] or 0),
        'avg_fulfillment_days': float(r[4] or 0) if r[4] else None,
        'completed_pos': r[5],
        'on_time_pos': r[6],
        'late_pos': r[7],
        'avg_days_late': float(r[8] or 0) if r[8] else None,
        'fulfillment_rate': float(r[9] or 0),
        'on_time_rate': float(r[10] or 0)
    } for r in results]

def get_overdue_pos():
    """Get overdue purchase orders"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        po.id,
        po.num,
        po.dateIssued,
        v.name as vendor_name,
        (SELECT MIN(poi.dateScheduledFulfillment)
         FROM poitem poi
         WHERE poi.poId = po.id
         AND poi.qtyToFulfill > poi.qtyFulfilled) as earliest_due_date,
        DATEDIFF(CURDATE(), (SELECT MIN(poi.dateScheduledFulfillment)
                              FROM poitem poi
                              WHERE poi.poId = po.id
                              AND poi.qtyToFulfill > poi.qtyFulfilled)) as days_overdue,
        (SELECT SUM(poi.totalCost) FROM poitem poi WHERE poi.poId = po.id) as total_value
    FROM po
    JOIN vendor v ON po.vendorId = v.id
    WHERE po.statusId IN (20, 30, 40)
    AND (SELECT MIN(poi.dateScheduledFulfillment)
         FROM poitem poi
         WHERE poi.poId = po.id
         AND poi.qtyToFulfill > poi.qtyFulfilled) < CURDATE()
    ORDER BY days_overdue DESC
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{
        'po_id': r[0],
        'po_num': r[1],
        'date_issued': r[2],
        'vendor_name': r[3],
        'earliest_due_date': r[4],
        'days_overdue': r[5],
        'total_value': float(r[6] or 0)
    } for r in results]

# ================================================================================
# INVENTORY HEALTH FUNCTIONS
# ================================================================================

def get_inventory_health_summary():
    """Get summary of inventory health metrics"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        COUNT(DISTINCT p.id) as total_parts,
        COUNT(DISTINCT CASE WHEN (SELECT SUM(t.qty) FROM tag t 
                                   JOIN location l ON t.locationId = l.id 
                                   WHERE t.partId = p.id AND t.qty > 0 
                                   AND l.countedAsAvailable = 1) > 0 THEN p.id END) as parts_with_stock,
        SUM((SELECT SUM(cl.totalCost) FROM tag t 
              JOIN location l ON t.locationId = l.id 
              JOIN costlayer cl ON cl.recordId = t.id
              WHERE t.partId = p.id AND t.qty > 0 
              AND l.countedAsAvailable = 1)) as total_inventory_value,
        COUNT(DISTINCT CASE WHEN (SELECT SUM(t.qty) FROM tag t 
                                   JOIN location l ON t.locationId = l.id 
                                   WHERE t.partId = p.id AND t.qty > 0 
                                   AND l.countedAsAvailable = 1) = 0 
                             AND p.activeFlag = 1 THEN p.id END) as zero_stock_parts,
        COUNT(DISTINCT CASE WHEN p.defaultBomId IS NOT NULL THEN p.id END) as manufactured_parts,
        COUNT(DISTINCT CASE WHEN p.defaultBomId IS NULL THEN p.id END) as purchased_parts
    FROM part p
    WHERE p.activeFlag = 1
    '''
    
    cursor.execute(query)
    result = cursor.fetchone()
    conn.close()
    
    return {
        'total_parts': result[0] or 0,
        'parts_with_stock': result[1] or 0,
        'total_inventory_value': float(result[2] or 0),
        'zero_stock_parts': result[3] or 0,
        'manufactured_parts': result[4] or 0,
        'purchased_parts': result[5] or 0
    }

def get_slow_moving_inventory(days_threshold=365):
    """Get slow-moving inventory (no movement in last N days)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        p.id,
        p.num,
        p.description,
        (SELECT SUM(t.qty) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         WHERE t.partId = p.id AND t.qty > 0 
         AND l.countedAsAvailable = 1) as qoh,
        (SELECT SUM(cl.totalCost) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         JOIN costlayer cl ON cl.recordId = t.id
         WHERE t.partId = p.id AND t.qty > 0 
         AND l.countedAsAvailable = 1) as inventory_value,
        (SELECT MAX(il.eventDate) FROM inventorylog il 
         WHERE il.partId = p.id 
         AND il.typeId IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)) as last_movement_date
    FROM part p
    WHERE p.activeFlag = 1
    AND (SELECT SUM(t.qty) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         WHERE t.partId = p.id AND t.qty > 0 
         AND l.countedAsAvailable = 1) > 0
    AND (SELECT MAX(il.eventDate) FROM inventorylog il 
         WHERE il.partId = p.id 
         AND il.typeId IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)) < DATE_SUB(CURDATE(), INTERVAL %s DAY)
    ORDER BY inventory_value DESC
    LIMIT 100
    '''
    
    cursor.execute(query, (days_threshold,))
    results = cursor.fetchall()
    conn.close()
    
    return [{
        'part_id': r[0],
        'part_num': r[1],
        'description': r[2] or '',
        'qoh': float(r[3] or 0),
        'inventory_value': float(r[4] or 0),
        'last_movement_date': r[5]
    } for r in results]

def get_excess_inventory():
    """Get parts with high inventory value (top 100 by value)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        p.id,
        p.num,
        p.description,
        (SELECT SUM(t.qty) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         WHERE t.partId = p.id AND t.qty > 0 
         AND l.countedAsAvailable = 1) as current_qoh,
        (SELECT SUM(cl.totalCost) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         JOIN costlayer cl ON cl.recordId = t.id
         WHERE t.partId = p.id AND t.qty > 0 
         AND l.countedAsAvailable = 1) as inventory_value
    FROM part p
    WHERE p.activeFlag = 1
    AND (SELECT SUM(t.qty) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         WHERE t.partId = p.id AND t.qty > 0 
         AND l.countedAsAvailable = 1) > 0
    ORDER BY inventory_value DESC
    LIMIT 100
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{
        'part_id': r[0],
        'part_num': r[1],
        'description': r[2] or '',
        'current_qoh': float(r[3] or 0),
        'inventory_value': float(r[4] or 0)
    } for r in results]

def get_zero_stock_active_parts():
    """Get active parts with zero stock"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        p.id,
        p.num,
        p.description,
        p.defaultBomId as has_bom,
        (SELECT COUNT(*) FROM soitem si 
         JOIN so ON si.soId = so.id 
         WHERE si.productId IN (SELECT pr.id FROM product pr WHERE pr.partId = p.id)
         AND so.statusId IN (10, 20, 30)) as open_so_count,
        (SELECT COUNT(*) FROM woitem wi 
         JOIN wo ON wi.woId = wo.id 
         WHERE wi.partId = p.id 
         AND wo.statusId IN (10, 30)) as open_wo_count
    FROM part p
    WHERE p.activeFlag = 1
    AND (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         WHERE t.partId = p.id AND t.qty > 0 
         AND l.countedAsAvailable = 1) = 0
    ORDER BY open_so_count DESC, open_wo_count DESC
    LIMIT 100
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{
        'part_id': r[0],
        'part_num': r[1],
        'description': r[2] or '',
        'has_bom': r[3] is not None,
        'open_so_count': r[4] or 0,
        'open_wo_count': r[5] or 0
    } for r in results]

def get_inventory_turnover():
    """Get inventory turnover by part (simplified - parts with recent usage)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        p.id,
        p.num,
        p.description,
        (SELECT SUM(t.qty) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         WHERE t.partId = p.id AND t.qty > 0 
         AND l.countedAsAvailable = 1) as avg_qoh,
        (SELECT COUNT(*) FROM inventorylog il 
         WHERE il.partId = p.id 
         AND il.typeId IN (3, 4, 5, 6)  -- Issue, Pick, Ship, etc.
         AND il.eventDate >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)) as transactions_90d
    FROM part p
    WHERE p.activeFlag = 1
    AND (SELECT SUM(t.qty) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         WHERE t.partId = p.id AND t.qty > 0 
         AND l.countedAsAvailable = 1) > 0
    HAVING transactions_90d > 0
    ORDER BY transactions_90d DESC
    LIMIT 50
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return [{
        'part_id': r[0],
        'part_num': r[1],
        'description': r[2] or '',
        'avg_qoh': float(r[3] or 0),
        'transactions_90d': r[4] or 0
    } for r in results]

# ================================================================================
# BOM COMPARISON FUNCTIONS
# ================================================================================

def get_part_info(part_num):
    """Get part details"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.id, p.num, p.description, p.defaultBomId, b.num as bom_num
        FROM part p
        LEFT JOIN bom b ON p.defaultBomId = b.id
        WHERE p.num = %s
    ''', (part_num,))
    result = cursor.fetchone()
    conn.close()
    return result

def get_bom_components_recursive(part_num, level=0, visited=None):
    """Recursively get all BOM components for a part"""
    if visited is None:
        visited = set()
    
    # Prevent infinite loops
    if part_num in visited:
        return []
    visited.add(part_num)
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT bi.partId, comp.num, comp.description, bi.quantity, u.code as uom, 
                   bit.name as item_type, comp.defaultBomId
            FROM part p
            JOIN bom b ON p.defaultBomId = b.id
            JOIN bomitem bi ON bi.bomId = b.id
            JOIN part comp ON bi.partId = comp.id
            JOIN uom u ON bi.uomId = u.id
            JOIN bomitemtype bit ON bi.typeId = bit.id
            WHERE p.num = %s
            AND comp.activeFlag = 1  -- Only include active items
            ORDER BY comp.num
        ''', (part_num,))
        
        results = cursor.fetchall()
        conn.close()
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        raise Exception(f"Error fetching BOM components for {part_num}: {str(e)}")
    
    components = []
    for row in results:
        part_id, comp_num, desc, qty, uom, item_type, has_bom = row
        
        if comp_num == part_num:
            continue
        
        components.append({
            'part_id': part_id,
            'part_num': comp_num,
            'description': desc or '',
            'quantity': float(qty),
            'uom': uom,
            'item_type': item_type,
            'level': level,
            'has_bom': has_bom is not None
        })
        
        if has_bom and level < 5:
            sub_components = get_bom_components_recursive(comp_num, level + 1, visited.copy())
            components.extend(sub_components)
    
    return components

def get_inventory_with_locations(part_id):
    """Get inventory quantities with location breakdown
    Only counts truly available stock locations (excludes Inspection, Manufacturing, Rework, etc.)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT l.name as location, lt.name as loc_type, lg.name as loc_group,
               t.qty, t.qtyCommitted, l.countedAsAvailable,
               CASE WHEN t.woItemId IS NOT NULL THEN 'WIP' ELSE 'Stock' END as inv_type,
               l.typeId as location_type_id
        FROM tag t
        JOIN location l ON t.locationId = l.id
        JOIN locationtype lt ON l.typeId = lt.id
        JOIN locationgroup lg ON l.locationGroupId = lg.id
        WHERE t.partId = %s AND t.qty > 0
        ORDER BY l.countedAsAvailable DESC, t.qty DESC
    ''', (part_id,))
    locations = cursor.fetchall()
    conn.close()
    
    # Calculate quantities correctly:
    # Available: Only count Stock/Store Front locations (excluding WIP, Inspect, Rework)
    # Committed: Sum of ALL committed quantities from ALL locations (global allocation)
    # WIP: Quantity in WIP locations (woItemId IS NOT NULL or Manufacturing type 80)
    # Total: Sum of ALL quantities from ALL locations
    
    available_qty = 0
    available_committed = 0  # Committed in available locations only
    total_committed = 0  # Committed from ALL locations (global)
    wip_qty = 0
    
    for row in locations:
        loc_name = row[0].lower() if row[0] else ''
        loc_type_id = row[7]
        is_countable = row[5]
        is_wip = row[6] == 'WIP'
        qty = row[3]
        committed = row[4]
        
        # Count committed from ALL locations (global allocation)
        total_committed += committed
        
        # Count WIP quantity - match Fishbowl's exact definition:
        # Only count locations with "WIP" in the name (like "Main-WIP")
        # Fishbowl shows WIP as inventory in WIP-named locations, not all Manufacturing locations
        # Tags tied to Work Orders (woItemId) in WIP locations are already counted via the location
        if 'wip' in loc_name:
            wip_qty += qty
        
        # Count available quantity only from truly available locations:
        # - countedAsAvailable = 1
        # - Location type is Stock (10) or Store Front (70)
        # - Not WIP (woItemId IS NULL)
        # - Not Inspection (50), Manufacturing (80), or other non-stock types
        # - Name doesn't contain "rework", "inspect", "repair"
        if (is_countable and 
            not is_wip and
            loc_type_id in (10, 70) and  # Only Stock and Store Front
            'rework' not in loc_name and
            'inspect' not in loc_name and
            'repair' not in loc_name):
            available_qty += qty  # Add qty
            available_committed += committed  # Add committed from available locations
    
    # Net available = Available quantity minus committed in available locations
    net_available_qty = available_qty - available_committed
    
    # Total quantity from all locations
    total_qty = sum(row[3] for row in locations)
    
    location_list = []
    for loc in locations:
        location_list.append({
            'name': loc[0],
            'type': loc[1],
            'group': loc[2],
            'qty': float(loc[3]),
            'committed': float(loc[4]),
            'countable': bool(loc[5]),
            'inv_type': loc[6]
        })
    
    return {
        'available': float(available_qty),  # Total qty in available locations (Stock/Store Front only)
        'committed': float(total_committed),  # Total committed from ALL locations (global allocation)
        'net_available': float(net_available_qty),  # Available - Committed in available locations (actual available)
        'wip': float(wip_qty),  # WIP quantity (tags tied to WO or Manufacturing locations)
        'total': float(total_qty),  # Total qty from ALL locations
        'locations': location_list
    }

def search_parts(query):
    """Search for parts by number or description"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.num, p.description, 
               CASE WHEN p.defaultBomId IS NOT NULL THEN 1 ELSE 0 END as has_bom
        FROM part p
        WHERE (p.num LIKE %s OR p.description LIKE %s)
        AND p.activeFlag = 1
        ORDER BY p.num
        LIMIT 20
    ''', (f'%{query}%', f'%{query}%'))
    results = cursor.fetchall()
    conn.close()
    return [{'num': r[0], 'description': r[1] or '', 'has_bom': bool(r[2])} for r in results]

def compare_boms(part_numbers, demand_quantities=None):
    """Compare BOMs of multiple parts and find common/unique components
    Args:
        part_numbers: List of part numbers to compare
        demand_quantities: Dict mapping part_num to demand quantity (e.g., {'29540011': 10, '29540031': 5})
    """
    if demand_quantities is None:
        demand_quantities = {}
    
    all_components = {}
    part_info = {}
    
    for part_num in part_numbers:
        info = get_part_info(part_num)
        if info:
            part_info[part_num] = {
                'id': info[0],
                'num': info[1],
                'description': info[2] or '',
                'bom_id': info[3],
                'bom_num': info[4]
            }
            components = get_bom_components_recursive(part_num)
            
            # Create lookup by part_num (first occurrence)
            comp_dict = {}
            for c in components:
                if c['part_num'] not in comp_dict:
                    comp_dict[c['part_num']] = c
            all_components[part_num] = comp_dict
        else:
            part_info[part_num] = None
            all_components[part_num] = {}
    
    # Find common components (in ALL parts)
    valid_parts = [pn for pn in part_numbers if all_components.get(pn)]
    if len(valid_parts) < 2:
        return {'error': 'Need at least 2 valid parts with BOMs to compare'}
    
    # Get intersection of all component sets
    common_nums = set(all_components[valid_parts[0]].keys())
    for part_num in valid_parts[1:]:
        common_nums &= set(all_components[part_num].keys())
    
    # Get unique components for each part
    unique_components = {}
    for part_num in valid_parts:
        unique_nums = set(all_components[part_num].keys()) - common_nums
        unique_components[part_num] = unique_nums
    
    # Build results with inventory data and order requirements
    common_results = []
    for comp_num in sorted(common_nums):
        # Get component info from first part
        comp = all_components[valid_parts[0]][comp_num]
        inv = get_inventory_with_locations(comp['part_id'])
        
        # Determine stock status
        if inv['net_available'] > 0:
            stock_status = 'In Stock'
        elif inv['wip'] > 0:
            stock_status = 'WIP Only'
        else:
            stock_status = 'Shortage'
        
        # Get quantity per each parent part
        qty_per_part = {}
        level_per_part = {}
        total_demand = 0.0
        for pn in valid_parts:
            if comp_num in all_components[pn]:
                qty_per_part[pn] = all_components[pn][comp_num]['quantity']
                level_per_part[pn] = all_components[pn][comp_num]['level']
                # Calculate total demand for this component
                demand = float(demand_quantities.get(pn, 0))
                total_demand += qty_per_part[pn] * demand
        
        # Calculate order requirement: demand - available
        order_required = max(0, total_demand - inv['net_available'])
        
        common_results.append({
            'part_num': comp_num,
            'description': comp['description'],
            'has_bom': comp['has_bom'],
            'qty_per_part': qty_per_part,
            'level_per_part': level_per_part,
            'available': inv['available'],
            'committed': inv['committed'],
            'net_available': inv['net_available'],
            'wip': inv['wip'],
            'total': inv['total'],
            'stock_status': stock_status,
            'locations': inv['locations'],
            'total_demand': total_demand,
            'order_required': order_required
        })
    
    # Build unique results for each part
    unique_results = {}
    for part_num in valid_parts:
        unique_results[part_num] = []
        demand = float(demand_quantities.get(part_num, 0))
        for comp_num in sorted(unique_components[part_num]):
            comp = all_components[part_num][comp_num]
            inv = get_inventory_with_locations(comp['part_id'])
            
            if inv['net_available'] > 0:
                stock_status = 'In Stock'
            elif inv['wip'] > 0:
                stock_status = 'WIP Only'
            else:
                stock_status = 'Shortage'
            
            # Calculate demand and order requirement for unique components
            component_demand = comp['quantity'] * demand
            order_required = max(0, component_demand - inv['net_available'])
            
            unique_results[part_num].append({
                'part_num': comp_num,
                'description': comp['description'],
                'has_bom': comp['has_bom'],
                'quantity': comp['quantity'],
                'level': comp['level'],
                'available': inv['available'],
                'committed': inv['committed'],
                'net_available': inv['net_available'],
                'wip': inv['wip'],
                'total': inv['total'],
                'stock_status': stock_status,
                'locations': inv['locations'],
                'total_demand': component_demand,
                'order_required': order_required
            })
    
    return {
        'part_info': part_info,
        'valid_parts': valid_parts,
        'common_count': len(common_nums),
        'common_components': common_results,
        'unique_components': unique_results,
        'total_per_part': {pn: len(all_components[pn]) for pn in valid_parts},
        'demand_quantities': demand_quantities
    }

# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Supply Chain Shortage KPI Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        :root {
            --bg-primary: #0a0e17;
            --bg-secondary: #111827;
            --bg-card: #1a2234;
            --text-primary: #f0f4f8;
            --text-secondary: #94a3b8;
            --accent-red: #ef4444;
            --accent-orange: #f97316;
            --accent-yellow: #eab308;
            --accent-green: #22c55e;
            --accent-blue: #3b82f6;
            --accent-purple: #8b5cf6;
            --border-color: #2d3748;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Space Grotesk', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            background-image: 
                radial-gradient(ellipse at top left, rgba(59, 130, 246, 0.1) 0%, transparent 50%),
                radial-gradient(ellipse at bottom right, rgba(139, 92, 246, 0.1) 0%, transparent 50%);
        }
        
        .container {
            max-width: 1600px;
            margin: 0 auto;
            padding: 2rem;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border-color);
        }
        
        .logo {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        
        .logo-icon {
            width: 48px;
            height: 48px;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
        }
        
        h1 {
            font-size: 1.75rem;
            font-weight: 700;
            background: linear-gradient(90deg, var(--text-primary), var(--accent-blue));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .subtitle {
            color: var(--text-secondary);
            font-size: 0.875rem;
        }
        
        .timestamp {
            color: var(--text-secondary);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.875rem;
        }
        
        .refresh-btn {
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            color: white;
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            cursor: pointer;
            font-family: inherit;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .refresh-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 20px rgba(59, 130, 246, 0.4);
        }
        
        .filter-group {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.75rem 1rem;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            transition: all 0.2s;
        }
        
        .filter-group:hover {
            background: var(--bg-secondary);
            border-color: var(--accent-blue);
        }
        
        .filter-group label {
            font-size: 0.875rem;
            color: var(--text-secondary);
            font-weight: 500;
        }
        
        .filter-group select {
            padding: 0.5rem 0.75rem;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            color: var(--text-primary);
            font-family: inherit;
            font-size: 0.875rem;
            cursor: pointer;
            transition: border-color 0.2s;
        }
        
        .filter-group select:focus {
            outline: none;
            border-color: var(--accent-blue);
        }
        
        .filter-group select option {
            background: var(--bg-card);
            color: var(--text-primary);
        }
        
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        .kpi-card {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 1.5rem;
            border: 1px solid var(--border-color);
            position: relative;
            overflow: hidden;
        }
        
        .kpi-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
        }
        
        .kpi-card.red::before { background: var(--accent-red); }
        .kpi-card.orange::before { background: var(--accent-orange); }
        .kpi-card.yellow::before { background: var(--accent-yellow); }
        .kpi-card.green::before { background: var(--accent-green); }
        
        .kpi-label {
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        .kpi-value {
            font-size: 2.5rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }
        
        .kpi-card.red .kpi-value { color: var(--accent-red); }
        .kpi-card.orange .kpi-value { color: var(--accent-orange); }
        .kpi-card.yellow .kpi-value { color: var(--accent-yellow); }
        .kpi-card.green .kpi-value { color: var(--accent-green); }
        
        .kpi-subtext {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 0.25rem;
        }
        
        .section-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        .section {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 1.5rem;
            border: 1px solid var(--border-color);
        }
        
        .section-title {
            font-size: 1.125rem;
            font-weight: 600;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .section-title .icon {
            width: 24px;
            height: 24px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.875rem;
        }
        
        .section-title .icon.red { background: rgba(239, 68, 68, 0.2); color: var(--accent-red); }
        .section-title .icon.orange { background: rgba(249, 115, 22, 0.2); color: var(--accent-orange); }
        .section-title .icon.blue { background: rgba(59, 130, 246, 0.2); color: var(--accent-blue); }
        .section-title .icon.purple { background: rgba(139, 92, 246, 0.2); color: var(--accent-purple); }
        
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.875rem;
        }
        
        th {
            text-align: left;
            padding: 0.75rem;
            color: var(--text-secondary);
            font-weight: 500;
            border-bottom: 1px solid var(--border-color);
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
            /* Keep column headers visible while scrolling */
            position: sticky;
            top: 0;
            background: var(--bg-card);
            z-index: 2;
        }
        
        td {
            padding: 0.75rem;
            border-bottom: 1px solid var(--border-color);
            position: relative;
        }
        
        tr:hover {
            background: rgba(255, 255, 255, 0.02);
        }
        
        .part-num {
            font-family: 'JetBrains Mono', monospace;
            color: var(--accent-blue);
        }
        
        .order-ref {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            color: var(--accent-purple);
            position: relative;
            display: inline-block;
        }
        
        .more-link {
            color: var(--accent-blue);
            cursor: pointer;
            text-decoration: underline;
            font-weight: 500;
        }
        
        .more-link:hover {
            color: var(--accent-purple);
        }
        
        .orders-dropdown {
            position: absolute;
            top: 100%;
            left: 0;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            padding: 0.5rem;
            margin-top: 0.25rem;
            z-index: 1000;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            color: var(--accent-purple);
            white-space: normal;
            max-width: 300px;
            min-width: 200px;
        }
        
        .badge {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        
        .badge.red { background: rgba(239, 68, 68, 0.2); color: var(--accent-red); }
        .badge.orange { background: rgba(249, 115, 22, 0.2); color: var(--accent-orange); }
        .badge.green { background: rgba(34, 197, 94, 0.2); color: var(--accent-green); }
        
        .trend-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 1.5rem;
        }
        
        .aging-bar {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.5rem;
        }
        
        .aging-label {
            width: 80px;
            font-size: 0.75rem;
            color: var(--text-secondary);
        }
        
        .aging-track {
            flex: 1;
            height: 24px;
            background: var(--bg-secondary);
            border-radius: 4px;
            overflow: hidden;
        }
        
        .aging-fill {
            height: 100%;
            display: flex;
            align-items: center;
            padding-left: 0.5rem;
            font-size: 0.75rem;
            font-weight: 600;
            color: white;
            transition: width 0.5s ease;
        }
        
        .aging-fill.green { background: var(--accent-green); }
        .aging-fill.yellow { background: var(--accent-yellow); }
        .aging-fill.orange { background: var(--accent-orange); }
        .aging-fill.red { background: var(--accent-red); }
        
        .recommendation {
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(139, 92, 246, 0.1));
            border: 1px solid var(--accent-blue);
            border-radius: 12px;
            padding: 1.25rem;
            margin-top: 2rem;
        }
        
        .recommendation h3 {
            color: var(--accent-blue);
            margin-bottom: 0.5rem;
        }
        
        .full-width {
            grid-column: 1 / -1;
        }
        
        .scroll-table {
            max-height: 400px;
            overflow-y: auto;
        }
        
        .scroll-table::-webkit-scrollbar {
            width: 8px;
        }
        
        .scroll-table::-webkit-scrollbar-track {
            background: var(--bg-secondary);
            border-radius: 4px;
        }
        
        .scroll-table::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 4px;
        }
        
        /* Tab styles for Weekly Trend */
        .tab-container {
            background: var(--bg-secondary);
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }
        
        .tab-header {
            display: flex;
            border-bottom: 1px solid var(--border-color);
        }
        
        .tab-btn {
            flex: 1;
            padding: 0.75rem 1rem;
            background: transparent;
            border: none;
            color: var(--text-secondary);
            font-family: inherit;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 0.875rem;
        }
        
        .tab-btn:hover {
            background: var(--bg-card);
            color: var(--text-primary);
        }
        
        .tab-btn.active {
            background: var(--bg-card);
            color: var(--accent-blue);
            border-bottom: 2px solid var(--accent-blue);
        }
        
        .tab-content {
            display: none;
            padding: 1rem;
        }
        
        .tab-content.active {
            display: block;
        }
        
        /* Chart containers */
        .chart-container {
            position: relative;
            height: 300px;
            margin-bottom: 1rem;
        }
        
        .chart-wrapper {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
            margin-bottom: 1rem;
        }
        
        @media (max-width: 1200px) {
            .kpi-grid { grid-template-columns: repeat(2, 1fr); }
            .section-grid { grid-template-columns: 1fr; }
            .trend-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Navigation Tabs -->
        <div style="display: flex; gap: 0.5rem; margin-bottom: 2rem; border-bottom: 1px solid var(--border-color); padding-bottom: 1rem;">
            <a href="/" style="padding: 0.75rem 1.5rem; background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple)); border-radius: 8px 8px 0 0; color: white; text-decoration: none; font-weight: 500;">📦 Shortage Dashboard</a>
            <a href="/po-management" style="padding: 0.75rem 1.5rem; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 8px 8px 0 0; color: var(--text-secondary); text-decoration: none; font-weight: 500;">📋 PO Management</a>
            <a href="/inventory-health" style="padding: 0.75rem 1.5rem; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 8px 8px 0 0; color: var(--text-secondary); text-decoration: none; font-weight: 500;">📊 Inventory Health</a>
            <a href="/bom-compare" style="padding: 0.75rem 1.5rem; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 8px 8px 0 0; color: var(--text-secondary); text-decoration: none; font-weight: 500;">🔍 BOM Comparison</a>
        </div>
        
        <header>
            <div class="logo">
                <div class="logo-icon">📦</div>
                <div>
                    <h1>Supply Chain Shortage KPI</h1>
                    <div class="subtitle">Metrohm Spectro - Real-time Picking Analysis</div>
                </div>
            </div>
            <div style="display: flex; align-items: center; gap: 1.5rem;">
                <form method="GET" action="/" style="display: flex; align-items: center; gap: 1rem; margin: 0;">
                    <div class="filter-group">
                        <label for="filter_mode">Filter B&W TEK SHANGHAI:</label>
                        <select id="filter_mode" name="filter_mode" onchange="this.form.submit()">
                            <option value="none" {% if filter_mode == 'none' %}selected{% endif %}>Show All</option>
                            <option value="include" {% if filter_mode == 'include' %}selected{% endif %}>Include Only</option>
                            <option value="exclude" {% if filter_mode == 'exclude' %}selected{% endif %}>Exclude</option>
                        </select>
                    </div>
                </form>
                <div class="timestamp">Last updated: {{ timestamp }}</div>
                <button class="refresh-btn" onclick="location.reload()">↻ Refresh</button>
            </div>
        </header>
        
        <!-- KPI Cards -->
        <div class="kpi-grid">
            <div class="kpi-card red">
                <div class="kpi-label">True Material Shortages</div>
                <div class="kpi-value">{{ true_count }}</div>
                <div class="kpi-subtext">{{ true_parts }} unique parts - ACTION REQUIRED</div>
            </div>
            <div class="kpi-card orange">
                <div class="kpi-label">WIP Shortages</div>
                <div class="kpi-value">{{ wip_count }}</div>
                <div class="kpi-subtext">{{ wip_parts }} unique parts - Waiting on MO/WO</div>
            </div>
            <div class="kpi-card green">
                <div class="kpi-label">Total Short Items</div>
                <div class="kpi-value">{{ total_count }}</div>
                <div class="kpi-subtext">{{ true_pct }}% true shortage rate</div>
            </div>
            <div class="kpi-card blue">
                <div class="kpi-label">Total Qty Short</div>
                <div class="kpi-value">{{ total_qty_short|int }}</div>
                <div class="kpi-subtext">Total pieces short - TRUE Material Shortages only</div>
            </div>
            <div class="kpi-card yellow">
                <div class="kpi-label">Other Issues</div>
                <div class="kpi-value">{{ other_count }}</div>
                <div class="kpi-subtext">{{ other_parts }} unique parts - Manufacturing/data issues (not supply chain)</div>
            </div>
        </div>
        
        <!-- Shortage Details -->
        <div class="section-grid">
            <div class="section">
                <div class="section-title">
                    <span class="icon red">⚠</span>
                    TRUE Material Shortages (Action Required){% if filter_mode == 'include' %} - B&W TEK SHANGHAI Only{% elif filter_mode == 'exclude' %} - Excluding B&W TEK SHANGHAI{% endif %}
                </div>
                <div class="scroll-table">
                    <table>
                        <thead>
                            <tr>
                                <th>Part Number</th>
                                <th>Description</th>
                                <th># Orders</th>
                                <th>Qty Short</th>
                                <th>Order Numbers</th>
                                <th>On PO</th>
                                <th>PO Numbers</th>
                                <th>PO Date</th>
                                <th>Stock Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for part in true_shortages %}
                            <tr>
                                <td class="part-num">{{ part.part_num }}</td>
                                <td>{{ part.description[:25] }}</td>
                                <td><span class="badge red">{{ part.order_count }}</span></td>
                                <td><span class="badge red">{{ part.total_qty_short|int }}</span></td>
                                <td>
                                    <span class="order-ref">
                                        {% if part.orders_visible %}
                                            {{ part.orders_visible|join(', ') }}
                                        {% else %}
                                            -
                                        {% endif %}
                                        {% if part.orders_hidden %}
                                            <span class="more-link" onclick="toggleOrders('orders-{{ loop.index0 }}')"> +{{ part.orders_hidden|length }} more</span>
                                            <div id="orders-{{ loop.index0 }}" class="orders-dropdown" style="display: none;">
                                                {{ part.orders_hidden|join(', ') }}
                                            </div>
                                        {% endif %}
                                    </span>
                                </td>
                                <td>
                                    {% if part.on_order_qty > 0 %}
                                    <span class="badge green">{{ part.on_order_qty|int }}</span>
                                    {% else %}
                                    <span class="badge red">0</span>
                                    {% endif %}
                                </td>
                                <td><span class="order-ref">{{ part.po_nums if part.po_nums else '-' }}</span></td>
                                <td>{{ part.po_date_scheduled if part.po_date_scheduled else '-' }}</td>
                                <td>
                                    {% if part.available_qty > 0 and part.net_available_qty <= 0 %}
                                    <span class="badge orange" title="Stock exists ({{ part.available_qty|int }}) but all committed ({{ part.committed_qty|int }})">Stock Committed</span>
                                    {% elif part.available_qty > 0 %}
                                    <span class="badge green" title="Stock available: {{ part.available_qty|int }}">In Stock</span>
                                    {% else %}
                                    <span class="badge red" title="No stock available">No Stock</span>
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">
                    <span class="icon orange">🔧</span>
                    WIP Shortages (Waiting on Manufacturing)
                </div>
                <div class="scroll-table">
                    <table>
                        <thead>
                            <tr>
                                <th>Part Number</th>
                                <th>Description</th>
                                <th># Orders</th>
                                <th>Qty Short</th>
                                <th>Order Numbers</th>
                                <th>WIP</th>
                                <th>Being Mfg</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for part in wip_shortages %}
                            <tr>
                                <td class="part-num">{{ part.part_num }}</td>
                                <td>{{ part.description[:22] }}</td>
                                <td><span class="badge orange">{{ part.order_count }}</span></td>
                                <td><span class="badge orange">{{ part.total_qty_short|int }}</span></td>
                                <td>
                                    <span class="order-ref">
                                        {% if part.orders_visible %}
                                            {{ part.orders_visible|join(', ') }}
                                        {% else %}
                                            -
                                        {% endif %}
                                        {% if part.orders_hidden %}
                                            <span class="more-link" onclick="toggleOrders('wip-orders-{{ loop.index0 }}')"> +{{ part.orders_hidden|length }} more</span>
                                            <div id="wip-orders-{{ loop.index0 }}" class="orders-dropdown" style="display: none;">
                                                {{ part.orders_hidden|join(', ') }}
                                            </div>
                                        {% endif %}
                                    </span>
                                </td>
                                <td>{{ part.wip|int }}</td>
                                <td><span class="badge orange">{{ part.being_mfg|int }}</span></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        
        <!-- Trends -->
        <div class="trend-grid">
            <div class="section">
                <div class="section-title">
                    <span class="icon blue">📅</span>
                    Weekly Trend
                </div>
                <div class="tab-container" style="margin-top: 1rem;">
                    <div class="tab-header">
                        <button class="tab-btn active" onclick="showWeeklyTab('current')">
                            Currently Open
                        </button>
                        <button class="tab-btn" onclick="showWeeklyTab('historical')">
                            Historical Total
                        </button>
                    </div>
                    <div class="tab-content active" id="weekly-current">
                        <div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                            Currently open shortages from picks created each week
                        </div>
                        <div class="chart-container">
                            <canvas id="weeklyCurrentChart"></canvas>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>Week</th>
                                    <th>Items</th>
                                    <th>Parts</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for week in weekly %}
                                <tr>
                                    <td>{{ week.week_start }}</td>
                                    <td>{{ week.short_items }}</td>
                                    <td>{{ week.unique_parts }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    <div class="tab-content" id="weekly-historical">
                        <div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                            All shortages that existed during each week (includes resolved ones) - from audit tables
                        </div>
                        <div class="chart-container">
                            <canvas id="weeklyHistoricalChart"></canvas>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>Week</th>
                                    <th>Items</th>
                                    <th>Parts</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for week in weekly_historical %}
                                <tr>
                                    <td>{{ week.week_start }}</td>
                                    <td>{{ week.short_items }}</td>
                                    <td>{{ week.unique_parts }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">
                    <span class="icon purple">📊</span>
                    Monthly Trend
                </div>
                <div class="tab-container" style="margin-top: 1rem;">
                    <div class="tab-header">
                        <button class="tab-btn active" onclick="showMonthlyTab('current')">
                            Currently Open
                        </button>
                        <button class="tab-btn" onclick="showMonthlyTab('historical')">
                            Historical Total
                        </button>
                    </div>
                    <div class="tab-content active" id="monthly-current">
                        <div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                            Currently open shortages from picks created each month
                        </div>
                        <div class="chart-container">
                            <canvas id="monthlyCurrentChart"></canvas>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>Month</th>
                                    <th>Items</th>
                                    <th>Parts</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for month in monthly %}
                                <tr>
                                    <td>{{ month.month }}</td>
                                    <td>{{ month.short_items }}</td>
                                    <td>{{ month.unique_parts }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    <div class="tab-content" id="monthly-historical">
                        <div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                            All shortages that existed during each month (includes resolved ones) - from audit tables
                        </div>
                        <div class="chart-container">
                            <canvas id="monthlyHistoricalChart"></canvas>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>Month</th>
                                    <th>Items</th>
                                    <th>Parts</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for month in monthly_historical %}
                                <tr>
                                    <td>{{ month.month }}</td>
                                    <td>{{ month.short_items }}</td>
                                    <td>{{ month.unique_parts }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">
                    <span class="icon green">📈</span>
                    Daily Trend
                </div>
                <div class="tab-container" style="margin-top: 1rem;">
                    <div class="tab-header">
                        <button class="tab-btn active" onclick="showDailyTab('current')">
                            Currently Open
                        </button>
                        <button class="tab-btn" onclick="showDailyTab('historical')">
                            Historical Total
                        </button>
                    </div>
                    <div class="tab-content active" id="daily-current">
                        <div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                            Currently open shortages from picks created each day
                        </div>
                        <div class="chart-container">
                            <canvas id="dailyCurrentChart"></canvas>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>Date</th>
                                    <th>Items</th>
                                    <th>Parts</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for day in daily %}
                                <tr>
                                    <td>{{ day.day_date }}</td>
                                    <td>{{ day.short_items }}</td>
                                    <td>{{ day.unique_parts }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    <div class="tab-content" id="daily-historical">
                        <div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                            All shortages that existed during each day (includes resolved ones) - from audit tables
                        </div>
                        <div class="chart-container">
                            <canvas id="dailyHistoricalChart"></canvas>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>Date</th>
                                    <th>Items</th>
                                    <th>Parts</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for day in daily_historical %}
                                <tr>
                                    <td>{{ day.day_date }}</td>
                                    <td>{{ day.short_items }}</td>
                                    <td>{{ day.unique_parts }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">
                    <span class="icon red">⏱</span>
                    Aging Analysis
                </div>
                {% for age in aging %}
                <div class="aging-bar">
                    <div class="aging-label">{{ age.bucket }}</div>
                    <div class="aging-track">
                        <div class="aging-fill {% if '60+' in age.bucket %}red{% elif '31-60' in age.bucket %}orange{% elif '15-30' in age.bucket %}yellow{% else %}green{% endif %}" 
                             style="width: {{ (age.short_items / total_count * 100)|int if total_count > 0 else 0 }}%">
                            {{ age.short_items }}
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        
        <!-- Recommendation -->
        <div class="recommendation">
            <h3>💡 Recommendation</h3>
            <p>Focus on the <strong>{{ true_count }} TRUE material shortages</strong> ({{ true_parts }} unique parts). 
               These require procurement action. The {{ wip_count }} WIP shortages will resolve when Manufacturing Orders complete.</p>
        </div>
    </div>
    
    <script>
        // Chart.js configuration
        Chart.defaults.color = '#94a3b8';
        Chart.defaults.borderColor = '#2d3748';
        Chart.defaults.backgroundColor = 'rgba(59, 130, 246, 0.1)';
        
        function showWeeklyTab(tabId) {
            const tabContainer = document.querySelector('#weekly-current')?.closest('.tab-container');
            if (tabContainer) {
                tabContainer.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
                tabContainer.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
                
                const btn = tabContainer.querySelector(`[onclick="showWeeklyTab('${tabId}')"]`);
                const content = document.getElementById(`weekly-${tabId}`);
                if (btn) btn.classList.add('active');
                if (content) content.classList.add('active');
                
                // Redraw chart when tab changes
                if (tabId === 'current' && window.weeklyCurrentChart) {
                    window.weeklyCurrentChart.update();
                } else if (tabId === 'historical' && window.weeklyHistoricalChart) {
                    window.weeklyHistoricalChart.update();
                }
            }
        }
        
        function showMonthlyTab(tabId) {
            const tabContainer = document.querySelector('#monthly-current')?.closest('.tab-container');
            if (tabContainer) {
                tabContainer.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
                tabContainer.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
                
                const btn = tabContainer.querySelector(`[onclick="showMonthlyTab('${tabId}')"]`);
                const content = document.getElementById(`monthly-${tabId}`);
                if (btn) btn.classList.add('active');
                if (content) content.classList.add('active');
                
                // Redraw chart when tab changes
                if (tabId === 'current' && window.monthlyCurrentChart) {
                    window.monthlyCurrentChart.update();
                } else if (tabId === 'historical' && window.monthlyHistoricalChart) {
                    window.monthlyHistoricalChart.update();
                }
            }
        }
        
        function toggleOrders(dropdownId) {
            const dropdown = document.getElementById(dropdownId);
            if (dropdown) {
                if (dropdown.style.display === 'none' || dropdown.style.display === '') {
                    dropdown.style.display = 'block';
                } else {
                    dropdown.style.display = 'none';
                }
            }
        }
        
        // Close dropdowns when clicking outside
        document.addEventListener('click', function(event) {
            if (!event.target.closest('.order-ref')) {
                document.querySelectorAll('.orders-dropdown').forEach(dropdown => {
                    dropdown.style.display = 'none';
                });
            }
        });
        
        // Weekly Current Chart
        const weeklyCurrentCtx = document.getElementById('weeklyCurrentChart');
        if (weeklyCurrentCtx) {
            const weeklyCurrentData = {
                labels: [{% for week in weekly %}'{{ week.week_start }}'{% if not loop.last %},{% endif %}{% endfor %}],
                datasets: [{
                    label: 'Shortage Items',
                    data: [{% for week in weekly %}{{ week.short_items }}{% if not loop.last %},{% endif %}{% endfor %}],
                    borderColor: 'rgb(59, 130, 246)',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    tension: 0.4,
                    fill: true
                }, {
                    label: 'Unique Parts',
                    data: [{% for week in weekly %}{{ week.unique_parts }}{% if not loop.last %},{% endif %}{% endfor %}],
                    borderColor: 'rgb(139, 92, 246)',
                    backgroundColor: 'rgba(139, 92, 246, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            };
            window.weeklyCurrentChart = new Chart(weeklyCurrentCtx, {
                type: 'line',
                data: weeklyCurrentData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'top' },
                        title: { display: false }
                    },
                    scales: {
                        y: { beginAtZero: true, grid: { color: 'rgba(45, 55, 72, 0.3)' } },
                        x: { grid: { color: 'rgba(45, 55, 72, 0.3)' } }
                    }
                }
            });
        }
        
        // Weekly Historical Chart
        const weeklyHistoricalCtx = document.getElementById('weeklyHistoricalChart');
        if (weeklyHistoricalCtx) {
            const weeklyHistoricalData = {
                labels: [{% for week in weekly_historical %}'{{ week.week_start }}'{% if not loop.last %},{% endif %}{% endfor %}],
                datasets: [{
                    label: 'Shortage Items',
                    data: [{% for week in weekly_historical %}{{ week.short_items }}{% if not loop.last %},{% endif %}{% endfor %}],
                    borderColor: 'rgb(239, 68, 68)',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    tension: 0.4,
                    fill: true
                }, {
                    label: 'Unique Parts',
                    data: [{% for week in weekly_historical %}{{ week.unique_parts }}{% if not loop.last %},{% endif %}{% endfor %}],
                    borderColor: 'rgb(249, 115, 22)',
                    backgroundColor: 'rgba(249, 115, 22, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            };
            window.weeklyHistoricalChart = new Chart(weeklyHistoricalCtx, {
                type: 'line',
                data: weeklyHistoricalData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'top' },
                        title: { display: false }
                    },
                    scales: {
                        y: { beginAtZero: true, grid: { color: 'rgba(45, 55, 72, 0.3)' } },
                        x: { grid: { color: 'rgba(45, 55, 72, 0.3)' } }
                    }
                }
            });
        }
        
        // Monthly Current Chart
        const monthlyCurrentCtx = document.getElementById('monthlyCurrentChart');
        if (monthlyCurrentCtx) {
            const monthlyCurrentData = {
                labels: [{% for month in monthly %}'{{ month.month }}'{% if not loop.last %},{% endif %}{% endfor %}],
                datasets: [{
                    label: 'Shortage Items',
                    data: [{% for month in monthly %}{{ month.short_items }}{% if not loop.last %},{% endif %}{% endfor %}],
                    borderColor: 'rgb(59, 130, 246)',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    tension: 0.4,
                    fill: true
                }, {
                    label: 'Unique Parts',
                    data: [{% for month in monthly %}{{ month.unique_parts }}{% if not loop.last %},{% endif %}{% endfor %}],
                    borderColor: 'rgb(139, 92, 246)',
                    backgroundColor: 'rgba(139, 92, 246, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            };
            window.monthlyCurrentChart = new Chart(monthlyCurrentCtx, {
                type: 'line',
                data: monthlyCurrentData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'top' },
                        title: { display: false }
                    },
                    scales: {
                        y: { beginAtZero: true, grid: { color: 'rgba(45, 55, 72, 0.3)' } },
                        x: { grid: { color: 'rgba(45, 55, 72, 0.3)' } }
                    }
                }
            });
        }
        
        // Monthly Historical Chart
        const monthlyHistoricalCtx = document.getElementById('monthlyHistoricalChart');
        if (monthlyHistoricalCtx) {
            const monthlyHistoricalData = {
                labels: [{% for month in monthly_historical %}'{{ month.month }}'{% if not loop.last %},{% endif %}{% endfor %}],
                datasets: [{
                    label: 'Shortage Items',
                    data: [{% for month in monthly_historical %}{{ month.short_items }}{% if not loop.last %},{% endif %}{% endfor %}],
                    borderColor: 'rgb(239, 68, 68)',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    tension: 0.4,
                    fill: true
                }, {
                    label: 'Unique Parts',
                    data: [{% for month in monthly_historical %}{{ month.unique_parts }}{% if not loop.last %},{% endif %}{% endfor %}],
                    borderColor: 'rgb(249, 115, 22)',
                    backgroundColor: 'rgba(249, 115, 22, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            };
            window.monthlyHistoricalChart = new Chart(monthlyHistoricalCtx, {
                type: 'line',
                data: monthlyHistoricalData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'top' },
                        title: { display: false }
                    },
                    scales: {
                        y: { beginAtZero: true, grid: { color: 'rgba(45, 55, 72, 0.3)' } },
                        x: { grid: { color: 'rgba(45, 55, 72, 0.3)' } }
                    }
                }
            });
        }
        
        function showDailyTab(tabId) {
            const tabContainer = document.querySelector('#daily-current')?.closest('.tab-container');
            if (tabContainer) {
                tabContainer.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
                tabContainer.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
                
                const btn = tabContainer.querySelector(`[onclick="showDailyTab('${tabId}')"]`);
                const content = document.getElementById(`daily-${tabId}`);
                if (btn) btn.classList.add('active');
                if (content) content.classList.add('active');
                
                // Redraw chart when tab changes
                if (tabId === 'current' && window.dailyCurrentChart) {
                    window.dailyCurrentChart.update();
                } else if (tabId === 'historical' && window.dailyHistoricalChart) {
                    window.dailyHistoricalChart.update();
                }
            }
        }
        
        // Daily Current Chart
        const dailyCurrentCtx = document.getElementById('dailyCurrentChart');
        if (dailyCurrentCtx) {
            const dailyCurrentData = {
                labels: [{% for day in daily %}'{{ day.day_date }}'{% if not loop.last %},{% endif %}{% endfor %}],
                datasets: [{
                    label: 'Shortage Items',
                    data: [{% for day in daily %}{{ day.short_items }}{% if not loop.last %},{% endif %}{% endfor %}],
                    borderColor: 'rgb(34, 197, 94)',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    tension: 0.4,
                    fill: true
                }, {
                    label: 'Unique Parts',
                    data: [{% for day in daily %}{{ day.unique_parts }}{% if not loop.last %},{% endif %}{% endfor %}],
                    borderColor: 'rgb(139, 92, 246)',
                    backgroundColor: 'rgba(139, 92, 246, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            };
            window.dailyCurrentChart = new Chart(dailyCurrentCtx, {
                type: 'line',
                data: dailyCurrentData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'top' },
                        title: { display: false }
                    },
                    scales: {
                        y: { beginAtZero: true, grid: { color: 'rgba(45, 55, 72, 0.3)' } },
                        x: { grid: { color: 'rgba(45, 55, 72, 0.3)' } }
                    }
                }
            });
        }
        
        // Daily Historical Chart
        const dailyHistoricalCtx = document.getElementById('dailyHistoricalChart');
        if (dailyHistoricalCtx) {
            const dailyHistoricalData = {
                labels: [{% for day in daily_historical %}'{{ day.day_date }}'{% if not loop.last %},{% endif %}{% endfor %}],
                datasets: [{
                    label: 'Shortage Items',
                    data: [{% for day in daily_historical %}{{ day.short_items }}{% if not loop.last %},{% endif %}{% endfor %}],
                    borderColor: 'rgb(239, 68, 68)',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    tension: 0.4,
                    fill: true
                }, {
                    label: 'Unique Parts',
                    data: [{% for day in daily_historical %}{{ day.unique_parts }}{% if not loop.last %},{% endif %}{% endfor %}],
                    borderColor: 'rgb(249, 115, 22)',
                    backgroundColor: 'rgba(249, 115, 22, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            };
            window.dailyHistoricalChart = new Chart(dailyHistoricalCtx, {
                type: 'line',
                data: dailyHistoricalData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'top' },
                        title: { display: false }
                    },
                    scales: {
                        y: { beginAtZero: true, grid: { color: 'rgba(45, 55, 72, 0.3)' } },
                        x: { grid: { color: 'rgba(45, 55, 72, 0.3)' } }
                    }
                }
            });
        }
    </script>
</body>
</html>
'''

@app.route('/')
def dashboard():
    # Get filter parameters
    filter_mode = request.args.get('filter_mode', 'none')  # 'none', 'include', 'exclude'
    filter_customer_id = 14 if filter_mode in ['include', 'exclude'] else None  # B&W TEK SHANGHAI customer ID
    exclude_mode = filter_mode == 'exclude'
    
    # Get data
    shortages = get_current_shortages()
    true_shortages, wip_shortages, other_shortages = categorize_shortages(shortages, filter_customer_id, exclude_mode)
    weekly = get_weekly_kpi()
    weekly_historical = get_weekly_kpi_historical()
    monthly = get_monthly_kpi()
    monthly_historical = get_monthly_kpi_historical()
    daily = get_daily_kpi()
    daily_historical = get_daily_kpi_historical()
    aging = get_aging()
    
    # Aggregate by part, collecting all order references
    true_by_part = {}
    for s in true_shortages:
        if s['part_num'] not in true_by_part:
            true_by_part[s['part_num']] = {
                'part_num': s['part_num'],
                'description': s['description'],
                'on_order_qty': s['on_order_qty'],
                'po_nums': s['po_nums'],
                'po_date_scheduled': s['po_date_scheduled'],
                'available_qty': s['available_qty'],
                'committed_qty': s['committed_qty'],
                'net_available_qty': s['net_available_qty'],
                'order_refs': set(),
                'count': 0,
                'total_qty_short': 0
            }
        true_by_part[s['part_num']]['count'] += 1
        true_by_part[s['part_num']]['total_qty_short'] += s['qty_short']
        if s['order_ref']:
            true_by_part[s['part_num']]['order_refs'].add(s['order_ref'])
        # Keep first non-empty PO info
        if s['po_nums'] and not true_by_part[s['part_num']]['po_nums']:
            true_by_part[s['part_num']]['po_nums'] = s['po_nums']
        if s['po_date_scheduled'] and not true_by_part[s['part_num']]['po_date_scheduled']:
            true_by_part[s['part_num']]['po_date_scheduled'] = s['po_date_scheduled']
    
    # Convert sets to strings and add order count
    for part in true_by_part.values():
        refs = sorted(part['order_refs'])
        part['all_orders'] = refs  # Store all orders
        part['orders'] = ', '.join(refs[:5]) if refs else '-'
        part['orders_visible'] = refs[:5]  # First 5 for display
        part['orders_hidden'] = refs[5:] if len(refs) > 5 else []  # Remaining orders
        part['order_count'] = len(part['order_refs'])
    
    wip_by_part = {}
    for s in wip_shortages:
        if s['part_num'] not in wip_by_part:
            wip_by_part[s['part_num']] = {
                'part_num': s['part_num'],
                'description': s['description'],
                'wip': s['wip_qty'],
                'being_mfg': s['being_mfg_qty'],
                'order_refs': set(),
                'count': 0,
                'total_qty_short': 0
            }
        wip_by_part[s['part_num']]['count'] += 1
        wip_by_part[s['part_num']]['total_qty_short'] += s['qty_short']
        if s['order_ref']:
            wip_by_part[s['part_num']]['order_refs'].add(s['order_ref'])
    
    # Convert sets to strings and add order count
    for part in wip_by_part.values():
        refs = sorted(part['order_refs'])
        part['all_orders'] = refs  # Store all orders
        part['orders'] = ', '.join(refs[:4]) if refs else '-'
        part['orders_visible'] = refs[:4]  # First 4 for display
        part['orders_hidden'] = refs[4:] if len(refs) > 4 else []  # Remaining orders
        part['order_count'] = len(part['order_refs'])
    
    total_count = len(shortages)
    true_pct = round(len(true_shortages) / total_count * 100, 1) if total_count > 0 else 0
    
    # Calculate total quantity short for TRUE Material Shortages only
    total_qty_short = sum(s['qty_short'] for s in true_shortages)
    
    return render_template_string(HTML_TEMPLATE,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        filter_mode=filter_mode,
        true_count=len(true_shortages),
        wip_count=len(wip_shortages),
        other_count=len(other_shortages),
        total_count=total_count,
        total_qty_short=total_qty_short,
        true_parts=len(true_by_part),
        wip_parts=len(wip_by_part),
        other_parts=len(set(s['part_id'] for s in other_shortages)),
        true_pct=true_pct,
        true_shortages=sorted(true_by_part.values(), key=lambda x: x['part_num']),
        wip_shortages=sorted(wip_by_part.values(), key=lambda x: x['part_num']),
        weekly=weekly[:8],
        weekly_historical=weekly_historical[:8],
        monthly=monthly[:6],
        monthly_historical=monthly_historical[:6],
        daily=daily[:30],
        daily_historical=daily_historical[:30],
        aging=aging
    )

@app.route('/api/data')
def api_data():
    """API endpoint for AJAX refresh"""
    shortages = get_current_shortages()
    true_shortages, wip_shortages, other_shortages = categorize_shortages(shortages)
    
    return jsonify({
        'true_count': len(true_shortages),
        'wip_count': len(wip_shortages),
        'other_count': len(other_shortages),
        'total_count': len(shortages),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

# ================================================================================
# BOM COMPARISON ROUTES
# ================================================================================

BOM_COMPARE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BOM Comparison Tool</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0e17;
            --bg-secondary: #111827;
            --bg-card: #1a2234;
            --text-primary: #f0f4f8;
            --text-secondary: #94a3b8;
            --accent-red: #ef4444;
            --accent-orange: #f97316;
            --accent-yellow: #eab308;
            --accent-green: #22c55e;
            --accent-blue: #3b82f6;
            --accent-purple: #8b5cf6;
            --accent-cyan: #06b6d4;
            --border-color: #2d3748;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Space Grotesk', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            background-image: 
                radial-gradient(ellipse at top left, rgba(59, 130, 246, 0.1) 0%, transparent 50%),
                radial-gradient(ellipse at bottom right, rgba(139, 92, 246, 0.1) 0%, transparent 50%);
        }
        
        .container { max-width: 1800px; margin: 0 auto; padding: 2rem; }
        
        /* Navigation Tabs */
        .nav-tabs {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1rem;
        }
        
        .nav-tab {
            padding: 0.75rem 1.5rem;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px 8px 0 0;
            color: var(--text-secondary);
            text-decoration: none;
            font-weight: 500;
            transition: all 0.2s;
        }
        
        .nav-tab:hover { background: var(--bg-card); color: var(--text-primary); }
        .nav-tab.active { 
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple)); 
            color: white; 
            border-color: transparent;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
        }
        
        .logo { display: flex; align-items: center; gap: 1rem; }
        
        .logo-icon {
            width: 48px; height: 48px;
            background: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue));
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.5rem;
        }
        
        h1 {
            font-size: 1.75rem;
            font-weight: 700;
            background: linear-gradient(90deg, var(--text-primary), var(--accent-cyan));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .subtitle { color: var(--text-secondary); font-size: 0.875rem; }
        
        /* Input Section */
        .input-section {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 1.5rem;
            border: 1px solid var(--border-color);
            margin-bottom: 2rem;
        }
        
        .input-title {
            font-size: 1.125rem;
            font-weight: 600;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .part-inputs {
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            align-items: flex-end;
        }
        
        .part-input-group {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }
        
        .part-input-group label {
            font-size: 0.875rem;
            color: var(--text-secondary);
        }
        
        .part-input {
            padding: 0.75rem 1rem;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.875rem;
            width: 200px;
            transition: border-color 0.2s;
        }
        
        .part-input:focus {
            outline: none;
            border-color: var(--accent-blue);
        }
        
        .part-input.valid { border-color: var(--accent-green); }
        .part-input.invalid { border-color: var(--accent-red); }
        
        .btn {
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-family: inherit;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            color: white;
        }
        
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 20px rgba(59, 130, 246, 0.4);
        }
        
        .btn-secondary {
            background: var(--bg-secondary);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
        }
        
        .btn-secondary:hover { background: var(--bg-card); }
        
        .btn-add {
            background: var(--accent-green);
            color: white;
            padding: 0.75rem 1rem;
        }
        
        .btn-remove {
            background: var(--accent-red);
            color: white;
            padding: 0.5rem 0.75rem;
            font-size: 0.875rem;
        }
        
        /* Results Section */
        .results-section {
            display: none;
        }
        
        .results-section.visible { display: block; }
        
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        .kpi-card {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 1.5rem;
            border: 1px solid var(--border-color);
            position: relative;
            overflow: hidden;
        }
        
        .kpi-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
        }
        
        .kpi-card.blue::before { background: var(--accent-blue); }
        .kpi-card.green::before { background: var(--accent-green); }
        .kpi-card.purple::before { background: var(--accent-purple); }
        .kpi-card.cyan::before { background: var(--accent-cyan); }
        .kpi-card.orange::before { background: var(--accent-orange); }
        
        .kpi-label {
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }
        
        .kpi-value {
            font-size: 2rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }
        
        .kpi-card.blue .kpi-value { color: var(--accent-blue); }
        .kpi-card.green .kpi-value { color: var(--accent-green); }
        .kpi-card.purple .kpi-value { color: var(--accent-purple); }
        .kpi-card.cyan .kpi-value { color: var(--accent-cyan); }
        .kpi-card.orange .kpi-value { color: var(--accent-orange); }
        
        .kpi-subtext {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 0.25rem;
        }
        
        /* Tabs */
        .tab-container {
            background: var(--bg-card);
            border-radius: 16px;
            border: 1px solid var(--border-color);
            overflow: hidden;
        }
        
        .tab-header {
            display: flex;
            border-bottom: 1px solid var(--border-color);
        }
        
        .tab-btn {
            flex: 1;
            padding: 1rem;
            background: transparent;
            border: none;
            color: var(--text-secondary);
            font-family: inherit;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .tab-btn:hover { background: var(--bg-secondary); color: var(--text-primary); }
        .tab-btn.active { 
            background: var(--bg-secondary); 
            color: var(--accent-blue);
            border-bottom: 2px solid var(--accent-blue);
        }
        
        .tab-content { display: none; padding: 1.5rem; }
        .tab-content.active { display: block; }
        
        /* Tables */
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.875rem;
        }
        
        th {
            text-align: left;
            padding: 0.75rem;
            color: var(--text-secondary);
            font-weight: 500;
            border-bottom: 1px solid var(--border-color);
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
            position: sticky;
            top: 0;
            background: var(--bg-card);
        }
        
        td {
            padding: 0.75rem;
            border-bottom: 1px solid var(--border-color);
        }
        
        tr:hover { background: rgba(255, 255, 255, 0.02); }
        
        .part-num {
            font-family: 'JetBrains Mono', monospace;
            color: var(--accent-blue);
        }
        
        .badge {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        
        .badge.green { background: rgba(34, 197, 94, 0.2); color: var(--accent-green); }
        .badge.red { background: rgba(239, 68, 68, 0.2); color: var(--accent-red); }
        .badge.orange { background: rgba(249, 115, 22, 0.2); color: var(--accent-orange); }
        .badge.blue { background: rgba(59, 130, 246, 0.2); color: var(--accent-blue); }
        .badge.purple { background: rgba(139, 92, 246, 0.2); color: var(--accent-purple); }
        
        .scroll-table {
            max-height: 500px;
            overflow-y: auto;
        }
        
        .scroll-table::-webkit-scrollbar { width: 8px; }
        .scroll-table::-webkit-scrollbar-track { background: var(--bg-secondary); border-radius: 4px; }
        .scroll-table::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 4px; }
        
        /* Location tooltip */
        .location-cell {
            position: relative;
            cursor: pointer;
        }
        
        .location-tooltip {
            display: none;
            position: absolute;
            bottom: 100%;
            left: 0;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 0.75rem;
            min-width: 300px;
            z-index: 100;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
        }
        
        .location-cell:hover .location-tooltip { display: block; }
        
        .location-tooltip table { font-size: 0.75rem; }
        .location-tooltip th, .location-tooltip td { padding: 0.5rem; }
        
        /* Part info cards */
        .part-info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        
        .part-info-card {
            background: var(--bg-secondary);
            border-radius: 8px;
            padding: 1rem;
            border-left: 3px solid var(--accent-blue);
        }
        
        .part-info-card h4 {
            font-family: 'JetBrains Mono', monospace;
            color: var(--accent-blue);
            margin-bottom: 0.5rem;
        }
        
        .part-info-card p {
            color: var(--text-secondary);
            font-size: 0.875rem;
        }
        
        .loading {
            display: none;
            text-align: center;
            padding: 2rem;
            color: var(--text-secondary);
        }
        
        .loading.visible { display: block; }
        
        .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid var(--border-color);
            border-top-color: var(--accent-blue);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 1rem;
        }
        
        @keyframes spin { to { transform: rotate(360deg); } }
        
        .error-message {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid var(--accent-red);
            color: var(--accent-red);
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
            display: none;
        }
        
        .error-message.visible { display: block; }
        
        @media (max-width: 1200px) {
            .kpi-grid { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Navigation -->
        <div class="nav-tabs">
            <a href="/" class="nav-tab">📦 Shortage Dashboard</a>
            <a href="/po-management" class="nav-tab">📋 PO Management</a>
            <a href="/inventory-health" class="nav-tab">📊 Inventory Health</a>
            <a href="/bom-compare" class="nav-tab active">🔍 BOM Comparison</a>
        </div>
        
        <header>
            <div class="logo">
                <div class="logo-icon">🔍</div>
                <div>
                    <h1>BOM Comparison Tool</h1>
                    <div class="subtitle">Compare Bill of Materials - Find Common & Unique Components</div>
                </div>
            </div>
        </header>
        
        <!-- Input Section -->
        <div class="input-section">
            <div class="input-title">
                <span>📋</span> Enter Part Numbers to Compare
            </div>
            <form id="compareForm">
                <div class="part-inputs" id="partInputs">
                    <div class="part-input-group">
                        <label>Part 1</label>
                        <input type="text" class="part-input" name="part" placeholder="e.g., 29540011" required>
                        <input type="number" class="part-input" name="demand" placeholder="Demand Qty" min="0" step="1" style="margin-top: 0.5rem; width: 200px;">
                    </div>
                    <div class="part-input-group">
                        <label>Part 2</label>
                        <input type="text" class="part-input" name="part" placeholder="e.g., 29540031" required>
                        <input type="number" class="part-input" name="demand" placeholder="Demand Qty" min="0" step="1" style="margin-top: 0.5rem; width: 200px;">
                    </div>
                    <button type="button" class="btn btn-add" onclick="addPartInput()">+ Add Part</button>
                    <button type="submit" class="btn btn-primary">🔍 Compare BOMs</button>
                </div>
            </form>
        </div>
        
        <!-- Error Message -->
        <div class="error-message" id="errorMessage"></div>
        
        <!-- Loading -->
        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p>Analyzing BOMs... This may take a moment for complex assemblies.</p>
        </div>
        
        <!-- Results Section -->
        <div class="results-section" id="results">
            <!-- Part Info -->
            <div class="part-info-grid" id="partInfoGrid"></div>
            
            <!-- Export Button -->
            <div style="display: flex; justify-content: flex-end; margin-bottom: 1rem;">
                <button class="btn btn-primary" id="exportBtn" onclick="exportToExcel()" style="display: none;">
                    📥 Export to Excel
                </button>
            </div>
            
            <!-- KPI Cards -->
            <div class="kpi-grid" id="kpiGrid"></div>
            
            <!-- Filter Section -->
            <div class="input-section" id="filterSection" style="display: none; margin-bottom: 1.5rem;">
                <div class="input-title">
                    <span>🔍</span> Filter Results
                </div>
                <div style="display: flex; gap: 1rem; flex-wrap: wrap; align-items: flex-end;">
                    <div class="part-input-group">
                        <label>Stock Status</label>
                        <select class="part-input" id="filterStockStatus" onchange="applyFilters()" style="width: 180px;">
                            <option value="all">All Status</option>
                            <option value="In Stock">In Stock Only</option>
                            <option value="Shortage">Shortage Only</option>
                            <option value="WIP Only">WIP Only</option>
                        </select>
                    </div>
                    <div class="part-input-group">
                        <label>Has Sub-BOM</label>
                        <select class="part-input" id="filterHasBom" onchange="applyFilters()" style="width: 150px;">
                            <option value="all">All</option>
                            <option value="yes">Yes (Sub-Assemblies)</option>
                            <option value="no">No (Raw Materials)</option>
                        </select>
                    </div>
                    <div class="part-input-group">
                        <label>Search Part Number</label>
                        <input type="text" class="part-input" id="filterPartNum" placeholder="Part number..." 
                               oninput="applyFilters()" style="width: 200px;">
                    </div>
                    <div class="part-input-group">
                        <label>Search Description</label>
                        <input type="text" class="part-input" id="filterDescription" placeholder="Description..." 
                               oninput="applyFilters()" style="width: 250px;">
                    </div>
                    <button type="button" class="btn btn-secondary" onclick="clearFilters()">
                        Clear Filters
                    </button>
                </div>
            </div>
            
            <!-- Tabs for Common/Unique -->
            <div class="tab-container">
                <div class="tab-header" id="tabHeader">
                    <button class="tab-btn active" onclick="showTab('common')">
                        Common Components
                    </button>
                </div>
                <div class="tab-content active" id="tab-common">
                    <div class="scroll-table">
                        <table id="commonTable">
                            <thead id="commonTableHead"></thead>
                            <tbody id="commonTableBody"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let partCount = 2;
        let currentData = null;
        let currentParts = [];
        let filteredCommonData = [];
        let filteredUniqueData = {};
        let totalDemandCommon = 0;
        let totalDemandUnique = {};
        
        function addPartInput() {
            partCount++;
            const container = document.getElementById('partInputs');
            const addBtn = container.querySelector('.btn-add');
            
            const group = document.createElement('div');
            group.className = 'part-input-group';
            group.innerHTML = `
                <label>Part ${partCount}</label>
                <input type="text" class="part-input" name="part" placeholder="Part number">
                <input type="number" class="part-input" name="demand" placeholder="Demand Qty" min="0" step="1" style="margin-top: 0.5rem; width: 200px;">
                <button type="button" class="btn btn-remove" onclick="removePartInput(this)" style="margin-top: 0.5rem;">✕</button>
            `;
            container.insertBefore(group, addBtn);
        }
        
        function removePartInput(btn) {
            btn.closest('.part-input-group').remove();
            // Renumber labels
            const groups = document.querySelectorAll('.part-input-group');
            groups.forEach((g, i) => {
                g.querySelector('label').textContent = `Part ${i + 1}`;
            });
            partCount = groups.length;
        }
        
        function updateKPICards(tabId) {
            if (!currentData) return;
            
            const validParts = currentData.valid_parts;
            
            // Use filtered data if available, otherwise use original data
            const commonData = filteredCommonData.length > 0 ? filteredCommonData : currentData.common_components;
            const inStock = commonData.filter(c => c.stock_status === 'In Stock').length;
            const shortage = commonData.filter(c => c.stock_status === 'Shortage').length;
            const subAsm = commonData.filter(c => c.has_bom).length;
            
            let totalDemand = 0;
            let demandLabel = 'Total Demand';
            
            if (tabId === 'common') {
                // Calculate total demand from filtered/common components
                totalDemand = commonData.reduce((sum, c) => sum + (c.total_demand || 0), 0);
                demandLabel = 'Total Demand (Common)';
            } else if (tabId.startsWith('unique-')) {
                // Extract part number from tabId (e.g., 'unique-29540011' -> '29540011')
                const partNum = validParts.find(p => 'unique-' + p.replace(/[^a-zA-Z0-9]/g, '_') === tabId);
                if (partNum) {
                    // Use filtered unique data if available, otherwise use original
                    const uniqueData = (filteredUniqueData[partNum] && filteredUniqueData[partNum].length > 0) 
                        ? filteredUniqueData[partNum] 
                        : currentData.unique_components[partNum];
                    totalDemand = uniqueData.reduce((sum, c) => sum + (c.total_demand || 0), 0);
                    demandLabel = `Total Demand (${partNum})`;
                }
            }
            
            document.getElementById('kpiGrid').innerHTML = `
                <div class="kpi-card blue">
                    <div class="kpi-label">Common Components</div>
                    <div class="kpi-value">${commonData.length}</div>
                </div>
                <div class="kpi-card green">
                    <div class="kpi-label">In Stock</div>
                    <div class="kpi-value">${inStock}</div>
                </div>
                <div class="kpi-card purple">
                    <div class="kpi-label">Sub-Assemblies</div>
                    <div class="kpi-value">${subAsm}</div>
                </div>
                <div class="kpi-card cyan">
                    <div class="kpi-label">Shortages</div>
                    <div class="kpi-value">${shortage}</div>
                </div>
                <div class="kpi-card orange">
                    <div class="kpi-label">${demandLabel}</div>
                    <div class="kpi-value">${totalDemand.toFixed(0)}</div>
                    <div class="kpi-subtext">Total pieces required</div>
                </div>
            `;
        }
        
        function showTab(tabId) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            
            document.querySelector(`[onclick="showTab('${tabId}')"]`).classList.add('active');
            document.getElementById(`tab-${tabId}`).classList.add('active');
            
            // Update KPI cards based on active tab
            updateKPICards(tabId);
        }
        
        document.getElementById('compareForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const partInputs = document.querySelectorAll('input[name="part"]');
            const demandInputs = document.querySelectorAll('input[name="demand"]');
            const parts = Array.from(partInputs).map(i => i.value.trim()).filter(v => v);
            
            if (parts.length < 2) {
                showError('Please enter at least 2 part numbers to compare');
                return;
            }
            
            // Collect demand quantities
            const demand_quantities = {};
            partInputs.forEach((input, index) => {
                const partNum = input.value.trim();
                if (partNum && demandInputs[index]) {
                    const demand = parseFloat(demandInputs[index].value) || 0;
                    if (demand > 0) {
                        demand_quantities[partNum] = demand;
                    }
                }
            });
            
            document.getElementById('errorMessage').classList.remove('visible');
            document.getElementById('results').classList.remove('visible');
            document.getElementById('loading').classList.add('visible');
            
            try {
                const response = await fetch('/api/bom-compare', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ parts: parts, demand_quantities: demand_quantities })
                });
                
                let data;
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('application/json')) {
                    data = await response.json();
                } else {
                    const text = await response.text();
                    showError('Server returned non-JSON response. Status: ' + response.status);
                    document.getElementById('loading').classList.remove('visible');
                    return;
                }
                
                if (!response.ok) {
                    showError(data.error || 'Server error: ' + response.status);
                    document.getElementById('loading').classList.remove('visible');
                    return;
                }
                
                if (data.error) {
                    showError(data.error);
                    document.getElementById('loading').classList.remove('visible');
                    return;
                }
                
                currentData = data;
                currentParts = parts;
                displayResults(data);
            } catch (error) {
                showError('Error comparing BOMs: ' + error.message);
            }
            
            document.getElementById('loading').classList.remove('visible');
        });
        
        function showError(message) {
            const el = document.getElementById('errorMessage');
            el.textContent = message;
            el.classList.add('visible');
        }
        
        function exportToExcel() {
            if (!currentData || !currentParts) {
                showError('No data to export');
                return;
            }
            
            // Create export request
            fetch('/api/bom-export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ parts: currentParts })
            })
            .then(response => {
                if (!response.ok) throw new Error('Export failed');
                return response.blob();
            })
            .then(blob => {
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `BOM_Comparison_${currentParts.join('_vs_')}_${new Date().toISOString().split('T')[0]}.csv`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
            })
            .catch(error => {
                showError('Export error: ' + error.message);
            });
        }
        
        function displayResults(data) {
            const validParts = data.valid_parts;
            
            // Show export button
            document.getElementById('exportBtn').style.display = 'block';
            
            // Part Info Cards
            const partInfoHtml = validParts.map(pn => {
                const info = data.part_info[pn];
                return `
                    <div class="part-info-card">
                        <h4>${info.num}</h4>
                        <p>${info.description}</p>
                        <p style="margin-top: 0.5rem; color: var(--accent-cyan);">
                            ${data.total_per_part[pn]} total components
                        </p>
                    </div>
                `;
            }).join('');
            document.getElementById('partInfoGrid').innerHTML = partInfoHtml;
            
            // Calculate total demand for common components
            totalDemandCommon = data.common_components.reduce((sum, c) => sum + (c.total_demand || 0), 0);
            
            // Calculate total demand for unique components per part
            totalDemandUnique = {};
            validParts.forEach(pn => {
                totalDemandUnique[pn] = data.unique_components[pn].reduce((sum, c) => sum + (c.total_demand || 0), 0);
            });
            
            // KPI Cards
            const inStock = data.common_components.filter(c => c.stock_status === 'In Stock').length;
            const shortage = data.common_components.filter(c => c.stock_status === 'Shortage').length;
            const subAsm = data.common_components.filter(c => c.has_bom).length;
            
            updateKPICards('common');
            
            // Tab Header - add unique tabs
            let tabHtml = `<button class="tab-btn active" onclick="showTab('common')">Common (${data.common_count})</button>`;
            validParts.forEach(pn => {
                const uniqueCount = data.unique_components[pn].length;
                const safeId = pn.replace(/[^a-zA-Z0-9]/g, '_');
                tabHtml += `<button class="tab-btn" onclick="showTab('unique-${safeId}')">Unique to ${pn} (${uniqueCount})</button>`;
            });
            document.getElementById('tabHeader').innerHTML = tabHtml;
            
            // Common Table Header
            let headerHtml = '<tr><th>Part Number</th><th>Description</th><th>Level</th>';
            validParts.forEach(pn => {
                headerHtml += `<th title="Quantity needed per 1 unit of ${pn}">Qty Per Unit<br><span style="font-size: 0.7em; font-weight: normal;">${pn.substring(0, 15)}</span></th>`;
            });
            headerHtml += '<th>Available</th><th>Committed</th><th>On Hand</th><th>WIP</th><th>Status</th><th>Demand</th><th>Order Required</th><th>Locations</th></tr>';
            document.getElementById('commonTableHead').innerHTML = headerHtml;
            
            // Common Table Body
            let bodyHtml = '';
            data.common_components.forEach(c => {
                const statusClass = c.stock_status === 'In Stock' ? 'green' : (c.stock_status === 'WIP Only' ? 'orange' : 'red');
                const hasBomBadge = c.has_bom ? '<span class="badge purple">BOM</span>' : '';
                
                let locTooltip = '';
                if (c.locations && c.locations.length > 0) {
                    locTooltip = `<div class="location-tooltip">
                        <table>
                            <tr><th>Location</th><th>Type</th><th>Qty</th><th>Committed</th></tr>
                            ${c.locations.map(l => `<tr>
                                <td>${l.name}</td>
                                <td>${l.type}</td>
                                <td>${l.qty.toFixed(0)}</td>
                                <td>${l.committed.toFixed(0)}</td>
                            </tr>`).join('')}
                        </table>
                    </div>`;
                }
                
                bodyHtml += `<tr>
                    <td class="part-num">${c.part_num} ${hasBomBadge}</td>
                    <td>${c.description.substring(0, 35)}</td>
                    <td>${Object.values(c.level_per_part)[0]}</td>`;
                
                validParts.forEach(pn => {
                    bodyHtml += `<td>${(c.qty_per_part[pn] || 0).toFixed(2)}</td>`;
                });
                
                // Get default location (first available location or first location)
                let defaultLocation = '-';
                if (c.locations && c.locations.length > 0) {
                    // Find first countable location, otherwise just use first
                    const countableLoc = c.locations.find(l => l.countable);
                    defaultLocation = countableLoc ? countableLoc.name : c.locations[0].name;
                    if (c.locations.length > 1) {
                        defaultLocation += ` (+${c.locations.length - 1})`;
                    }
                }
                
                const demand = (c.total_demand || 0).toFixed(0);
                const orderRequired = (c.order_required || 0).toFixed(0);
                const orderRequiredClass = parseFloat(orderRequired) > 0 ? 'red' : 'green';
                
                bodyHtml += `
                    <td>${c.net_available.toFixed(0)}</td>
                    <td>${c.committed.toFixed(0)}</td>
                    <td>${c.total.toFixed(0)}</td>
                    <td>${c.wip.toFixed(0)}</td>
                    <td><span class="badge ${statusClass}">${c.stock_status}</span></td>
                    <td>${demand}</td>
                    <td><span class="badge ${orderRequiredClass}">${orderRequired}</span></td>
                    <td title="${c.locations && c.locations.length > 0 ? c.locations.map(l => l.name + ' (' + l.qty + ')').join(', ') : ''}">
                        ${defaultLocation}
                    </td>
                </tr>`;
            });
            document.getElementById('commonTableBody').innerHTML = bodyHtml;
            
            // Create unique tabs content
            const tabContainer = document.querySelector('.tab-container');
            // Remove old unique tabs
            document.querySelectorAll('[id^="tab-unique"]').forEach(el => el.remove());
            
            validParts.forEach(pn => {
                const tabId = 'unique-' + pn.replace(/[^a-zA-Z0-9]/g, '_');
                const uniqueComponents = data.unique_components[pn];
                
                let tableHtml = `
                    <div class="tab-content" id="tab-${tabId}">
                        <div class="scroll-table">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Part Number</th>
                                        <th>Description</th>
                                        <th>Level</th>
                                        <th>Qty</th>
                                        <th>Available</th>
                                        <th>Committed</th>
                                        <th>On Hand</th>
                                        <th>WIP</th>
                                        <th>Status</th>
                                        <th>Demand</th>
                                        <th>Order Required</th>
                                        <th>Locations</th>
                                    </tr>
                                </thead>
                                <tbody>`;
                
                uniqueComponents.forEach(c => {
                    const statusClass = c.stock_status === 'In Stock' ? 'green' : (c.stock_status === 'WIP Only' ? 'orange' : 'red');
                    const hasBomBadge = c.has_bom ? '<span class="badge purple">BOM</span>' : '';
                    
                    let locTooltip = '';
                    if (c.locations && c.locations.length > 0) {
                        locTooltip = `<div class="location-tooltip">
                            <table>
                                <tr><th>Location</th><th>Type</th><th>Qty</th></tr>
                                ${c.locations.map(l => `<tr>
                                    <td>${l.name}</td>
                                    <td>${l.type}</td>
                                    <td>${l.qty.toFixed(0)}</td>
                                </tr>`).join('')}
                            </table>
                        </div>`;
                    }
                    
                    // Get default location for unique components
                    let defaultLoc = '-';
                    if (c.locations && c.locations.length > 0) {
                        const countableLoc = c.locations.find(l => l.countable);
                        defaultLoc = countableLoc ? countableLoc.name : c.locations[0].name;
                        if (c.locations.length > 1) {
                            defaultLoc += ` (+${c.locations.length - 1})`;
                        }
                    }
                    
                    const demand = (c.total_demand || 0).toFixed(0);
                    const orderRequired = (c.order_required || 0).toFixed(0);
                    const orderRequiredClass = parseFloat(orderRequired) > 0 ? 'red' : 'green';
                    
                    tableHtml += `<tr>
                        <td class="part-num">${c.part_num} ${hasBomBadge}</td>
                        <td>${c.description.substring(0, 40)}</td>
                        <td>${c.level}</td>
                        <td>${c.quantity.toFixed(2)}</td>
                        <td>${c.net_available.toFixed(0)}</td>
                        <td>${c.committed.toFixed(0)}</td>
                        <td>${c.total.toFixed(0)}</td>
                        <td>${c.wip.toFixed(0)}</td>
                        <td><span class="badge ${statusClass}">${c.stock_status}</span></td>
                        <td>${demand}</td>
                        <td><span class="badge ${orderRequiredClass}">${orderRequired}</span></td>
                        <td title="${c.locations && c.locations.length > 0 ? c.locations.map(l => l.name + ' (' + l.qty + ')').join(', ') : ''}">
                            ${defaultLoc}
                        </td>
                    </tr>`;
                });
                
                tableHtml += '</tbody></table></div></div>';
                tabContainer.insertAdjacentHTML('beforeend', tableHtml);
            });
            
            document.getElementById('results').classList.add('visible');
            document.getElementById('filterSection').style.display = 'block';
            
            // Store original data for filtering
            filteredCommonData = data.common_components.slice();
            filteredUniqueData = {};
            for (let pn in data.unique_components) {
                filteredUniqueData[pn] = data.unique_components[pn].slice();
            }
        }
        
        function applyFilters() {
            if (!currentData) return;
            
            const stockStatus = document.getElementById('filterStockStatus').value;
            const hasBom = document.getElementById('filterHasBom').value;
            const partNumFilter = document.getElementById('filterPartNum').value.toLowerCase().trim();
            const descFilter = document.getElementById('filterDescription').value.toLowerCase().trim();
            
            // Filter common components
            filteredCommonData = currentData.common_components.filter(c => {
                // Stock status filter
                if (stockStatus !== 'all' && c.stock_status !== stockStatus) return false;
                
                // Has BOM filter
                if (hasBom === 'yes' && !c.has_bom) return false;
                if (hasBom === 'no' && c.has_bom) return false;
                
                // Part number filter
                if (partNumFilter && !c.part_num.toLowerCase().includes(partNumFilter)) return false;
                
                // Description filter
                if (descFilter && !c.description.toLowerCase().includes(descFilter)) return false;
                
                return true;
            });
            
            // Filter unique components for each part
            const validParts = currentData.valid_parts;
            filteredUniqueData = {};
            validParts.forEach(pn => {
                filteredUniqueData[pn] = currentData.unique_components[pn].filter(c => {
                    if (stockStatus !== 'all' && c.stock_status !== stockStatus) return false;
                    if (hasBom === 'yes' && !c.has_bom) return false;
                    if (hasBom === 'no' && c.has_bom) return false;
                    if (partNumFilter && !c.part_num.toLowerCase().includes(partNumFilter)) return false;
                    if (descFilter && !c.description.toLowerCase().includes(descFilter)) return false;
                    return true;
                });
            });
            
            // Re-render tables with filtered data
            renderFilteredTables();
            
            // Update KPI cards based on active tab
            const activeTab = document.querySelector('.tab-btn.active');
            if (activeTab) {
                const tabId = activeTab.getAttribute('onclick').match(/'([^']+)'/)[1];
                updateKPICards(tabId);
            }
        }
        
        function clearFilters() {
            document.getElementById('filterStockStatus').value = 'all';
            document.getElementById('filterHasBom').value = 'all';
            document.getElementById('filterPartNum').value = '';
            document.getElementById('filterDescription').value = '';
            
            // Reset to original data
            filteredCommonData = currentData.common_components.slice();
            filteredUniqueData = {};
            for (let pn in currentData.unique_components) {
                filteredUniqueData[pn] = currentData.unique_components[pn].slice();
            }
            
            renderFilteredTables();
            
            // Update KPI cards based on active tab
            const activeTab = document.querySelector('.tab-btn.active');
            if (activeTab) {
                const tabId = activeTab.getAttribute('onclick').match(/'([^']+)'/)[1];
                updateKPICards(tabId);
            }
        }
        
        function renderFilteredTables() {
            if (!currentData) return;
            
            const validParts = currentData.valid_parts;
            
            // Update common table
            let bodyHtml = '';
            filteredCommonData.forEach(c => {
                const statusClass = c.stock_status === 'In Stock' ? 'green' : (c.stock_status === 'WIP Only' ? 'orange' : 'red');
                const hasBomBadge = c.has_bom ? '<span class="badge purple">BOM</span>' : '';
                
                let defaultLocation = '-';
                if (c.locations && c.locations.length > 0) {
                    const countableLoc = c.locations.find(l => l.countable);
                    defaultLocation = countableLoc ? countableLoc.name : c.locations[0].name;
                    if (c.locations.length > 1) {
                        defaultLocation += ` (+${c.locations.length - 1})`;
                    }
                }
                
                bodyHtml += `<tr>
                    <td class="part-num">${c.part_num} ${hasBomBadge}</td>
                    <td>${c.description.substring(0, 35)}</td>
                    <td>${Object.values(c.level_per_part)[0]}</td>`;
                
                validParts.forEach(pn => {
                    bodyHtml += `<td>${(c.qty_per_part[pn] || 0).toFixed(2)}</td>`;
                });
                
                const demand = (c.total_demand || 0).toFixed(0);
                const orderRequired = (c.order_required || 0).toFixed(0);
                const orderRequiredClass = parseFloat(orderRequired) > 0 ? 'red' : 'green';
                
                bodyHtml += `
                    <td>${c.available.toFixed(0)}</td>
                    <td>${c.committed.toFixed(0)}</td>
                    <td>${c.net_available.toFixed(0)}</td>
                    <td>${c.wip.toFixed(0)}</td>
                    <td><span class="badge ${statusClass}">${c.stock_status}</span></td>
                    <td>${demand}</td>
                    <td><span class="badge ${orderRequiredClass}">${orderRequired}</span></td>
                    <td title="${c.locations && c.locations.length > 0 ? c.locations.map(l => l.name + ' (' + l.qty + ')').join(', ') : ''}">
                        ${defaultLocation}
                    </td>
                </tr>`;
            });
            document.getElementById('commonTableBody').innerHTML = bodyHtml;
            
            // Update unique tables
            const tabContainer = document.querySelector('.tab-container');
            document.querySelectorAll('[id^="tab-unique"]').forEach(el => {
                const tabId = el.id.replace('tab-', '');
                const pn = validParts.find(p => 'unique-' + p.replace(/[^a-zA-Z0-9]/g, '_') === tabId);
                if (!pn || !filteredUniqueData[pn]) return;
                
                const tbody = el.querySelector('tbody');
                if (!tbody) return;
                
                let tableHtml = '';
                filteredUniqueData[pn].forEach(c => {
                    const statusClass = c.stock_status === 'In Stock' ? 'green' : (c.stock_status === 'WIP Only' ? 'orange' : 'red');
                    const hasBomBadge = c.has_bom ? '<span class="badge purple">BOM</span>' : '';
                    
                    let defaultLoc = '-';
                    if (c.locations && c.locations.length > 0) {
                        const countableLoc = c.locations.find(l => l.countable);
                        defaultLoc = countableLoc ? countableLoc.name : c.locations[0].name;
                        if (c.locations.length > 1) {
                            defaultLoc += ` (+${c.locations.length - 1})`;
                        }
                    }
                    
                    const demand = (c.total_demand || 0).toFixed(0);
                    const orderRequired = (c.order_required || 0).toFixed(0);
                    const orderRequiredClass = parseFloat(orderRequired) > 0 ? 'red' : 'green';
                    
                    tableHtml += `<tr>
                        <td class="part-num">${c.part_num} ${hasBomBadge}</td>
                        <td>${c.description.substring(0, 40)}</td>
                        <td>${c.level}</td>
                        <td>${c.quantity.toFixed(2)}</td>
                        <td>${c.available.toFixed(0)}</td>
                        <td>${c.committed.toFixed(0)}</td>
                        <td>${c.net_available.toFixed(0)}</td>
                        <td>${c.wip.toFixed(0)}</td>
                        <td><span class="badge ${statusClass}">${c.stock_status}</span></td>
                        <td>${demand}</td>
                        <td><span class="badge ${orderRequiredClass}">${orderRequired}</span></td>
                        <td title="${c.locations && c.locations.length > 0 ? c.locations.map(l => l.name + ' (' + l.qty + ')').join(', ') : ''}">
                            ${defaultLoc}
                        </td>
                    </tr>`;
                });
                tbody.innerHTML = tableHtml;
            });
            
            // Update tab counts
            const tabHeader = document.getElementById('tabHeader');
            let tabHtml = `<button class="tab-btn active" onclick="showTab('common')">Common (${filteredCommonData.length})</button>`;
            validParts.forEach(pn => {
                const uniqueCount = filteredUniqueData[pn] ? filteredUniqueData[pn].length : 0;
                const safeId = pn.replace(/[^a-zA-Z0-9]/g, '_');
                tabHtml += `<button class="tab-btn" onclick="showTab('unique-${safeId}')">Unique to ${pn} (${uniqueCount})</button>`;
            });
            tabHeader.innerHTML = tabHtml;
        }
    </script>
</body>
</html>
'''

@app.route('/bom-compare')
def bom_compare():
    """BOM Comparison page"""
    return render_template_string(BOM_COMPARE_TEMPLATE)

@app.route('/api/bom-compare', methods=['POST'])
def api_bom_compare():
    """API endpoint for BOM comparison"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        parts = data.get('parts', [])
        demand_quantities = data.get('demand_quantities', {})  # Dict of part_num -> quantity
        
        if len(parts) < 2:
            return jsonify({'error': 'Need at least 2 part numbers to compare'}), 400
        
        result = compare_boms(parts, demand_quantities)
        return jsonify(result)
    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback.print_exc()  # Print to console for debugging
        return jsonify({'error': f'Error comparing BOMs: {error_msg}'}), 500

@app.route('/api/search-parts')
def api_search_parts():
    """API endpoint for part search"""
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify([])
    
    results = search_parts(query)
    return jsonify(results)

@app.route('/api/bom-export', methods=['POST'])
def api_bom_export():
    """API endpoint to export BOM comparison to CSV"""
    data = request.get_json()
    parts = data.get('parts', [])
    
    if len(parts) < 2:
        return jsonify({'error': 'Need at least 2 part numbers to export'}), 400
    
    result = compare_boms(parts)
    
    if 'error' in result:
        return jsonify(result), 400
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header with part info
    writer.writerow(['BOM COMPARISON EXPORT'])
    writer.writerow(['Generated:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow([''])
    
    # Part information
    writer.writerow(['Part Information'])
    writer.writerow(['Part Number', 'Description', 'Total Components'])
    for pn in result['valid_parts']:
        info = result['part_info'][pn]
        writer.writerow([info['num'], info['description'], result['total_per_part'][pn]])
    writer.writerow([''])
    
    # Common components
    writer.writerow(['COMMON COMPONENTS'])
    writer.writerow(['Part Number', 'Description', 'Has Sub-BOM', 
                     'Level'] + [f'Qty Per Unit ({pn})' for pn in result['valid_parts']] + 
                     ['Available Qty', 'Committed Qty', 'Net Available', 'WIP Qty', 
                      'Total Inventory', 'Stock Status', 'Default Location', 'All Locations'])
    
    for c in result['common_components']:
        # Get default location
        default_loc = '-'
        all_locs = '-'
        if c['locations'] and len(c['locations']) > 0:
            countable_loc = next((l for l in c['locations'] if l.get('countable')), None)
            default_loc = countable_loc['name'] if countable_loc else c['locations'][0]['name']
            all_locs = '; '.join([f"{l['name']} ({l['qty']:.0f})" for l in c['locations']])
        
        qty_cols = [str(c['qty_per_part'].get(pn, 0)) for pn in result['valid_parts']]
        level = str(list(c['level_per_part'].values())[0]) if c['level_per_part'] else ''
        
        writer.writerow([
            c['part_num'],
            c['description'],
            'Yes' if c['has_bom'] else 'No',
            level
        ] + qty_cols + [
            f"{c['available']:.0f}",
            f"{c['committed']:.0f}",
            f"{c['net_available']:.0f}",
            f"{c['wip']:.0f}",
            f"{c['total']:.0f}",
            c['stock_status'],
            default_loc,
            all_locs
        ])
    
    writer.writerow([''])
    
    # Unique components for each part
    for pn in result['valid_parts']:
        writer.writerow([f'UNIQUE TO {pn}'])
        writer.writerow(['Part Number', 'Description', 'Has Sub-BOM', 'Level', 'Qty',
                         'Available Qty', 'Committed Qty', 'Net Available', 'WIP Qty',
                         'Total Inventory', 'Stock Status', 'Default Location', 'All Locations'])
        
        for c in result['unique_components'][pn]:
            default_loc = '-'
            all_locs = '-'
            if c['locations'] and len(c['locations']) > 0:
                countable_loc = next((l for l in c['locations'] if l.get('countable')), None)
                default_loc = countable_loc['name'] if countable_loc else c['locations'][0]['name']
                all_locs = '; '.join([f"{l['name']} ({l['qty']:.0f})" for l in c['locations']])
            
            writer.writerow([
                c['part_num'],
                c['description'],
                'Yes' if c['has_bom'] else 'No',
                str(c['level']),
                f"{c['quantity']:.2f}",
                f"{c['available']:.0f}",
                f"{c['committed']:.0f}",
                f"{c['net_available']:.0f}",
                f"{c['wip']:.0f}",
                f"{c['total']:.0f}",
                c['stock_status'],
                default_loc,
                all_locs
            ])
        
        writer.writerow([''])
    
    # Prepare response
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=BOM_Comparison_{"_vs_".join(parts)}_{datetime.now().strftime("%Y%m%d")}.csv'}
    )

# ================================================================================
# PURCHASE ORDER MANAGEMENT ROUTES
# ================================================================================

PO_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Purchase Order Management Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        :root {
            --bg-primary: #0a0e17;
            --bg-secondary: #111827;
            --bg-card: #1a2234;
            --text-primary: #f0f4f8;
            --text-secondary: #94a3b8;
            --accent-red: #ef4444;
            --accent-orange: #f97316;
            --accent-yellow: #eab308;
            --accent-green: #22c55e;
            --accent-blue: #3b82f6;
            --accent-purple: #8b5cf6;
            --border-color: #2d3748;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Space Grotesk', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            background-image: 
                radial-gradient(ellipse at top left, rgba(59, 130, 246, 0.1) 0%, transparent 50%),
                radial-gradient(ellipse at bottom right, rgba(139, 92, 246, 0.1) 0%, transparent 50%);
        }
        
        .container { max-width: 1800px; margin: 0 auto; padding: 2rem; }
        
        .nav-tabs {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1rem;
        }
        
        .nav-tab {
            padding: 0.75rem 1.5rem;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px 8px 0 0;
            color: var(--text-secondary);
            text-decoration: none;
            font-weight: 500;
            transition: all 0.2s;
        }
        
        .nav-tab:hover { background: var(--bg-card); color: var(--text-primary); }
        .nav-tab.active { 
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple)); 
            color: white; 
            border-color: transparent;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
        }
        
        .logo { display: flex; align-items: center; gap: 1rem; }
        
        .logo-icon {
            width: 48px; height: 48px;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.5rem;
        }
        
        h1 {
            font-size: 1.75rem;
            font-weight: 700;
            background: linear-gradient(90deg, var(--text-primary), var(--accent-blue));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .subtitle { color: var(--text-secondary); font-size: 0.875rem; }
        
        .timestamp {
            color: var(--text-secondary);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.875rem;
        }
        
        .refresh-btn {
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            color: white;
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            cursor: pointer;
            font-family: inherit;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .refresh-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 20px rgba(59, 130, 246, 0.4);
        }
        
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        .kpi-card {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 1.5rem;
            border: 1px solid var(--border-color);
            position: relative;
            overflow: hidden;
        }
        
        .kpi-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
        }
        
        .kpi-card.blue::before { background: var(--accent-blue); }
        .kpi-card.green::before { background: var(--accent-green); }
        .kpi-card.orange::before { background: var(--accent-orange); }
        .kpi-card.red::before { background: var(--accent-red); }
        .kpi-card.purple::before { background: var(--accent-purple); }
        
        .kpi-label {
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }
        
        .kpi-value {
            font-size: 2rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }
        
        .kpi-card.blue .kpi-value { color: var(--accent-blue); }
        .kpi-card.green .kpi-value { color: var(--accent-green); }
        .kpi-card.orange .kpi-value { color: var(--accent-orange); }
        .kpi-card.red .kpi-value { color: var(--accent-red); }
        .kpi-card.purple .kpi-value { color: var(--accent-purple); }
        
        .kpi-subtext {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 0.25rem;
        }
        
        .section {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 1.5rem;
            border: 1px solid var(--border-color);
            margin-bottom: 1.5rem;
        }
        
        .section-title {
            font-size: 1.125rem;
            font-weight: 600;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.875rem;
        }
        
        th {
            text-align: left;
            padding: 0.75rem;
            color: var(--text-secondary);
            font-weight: 500;
            border-bottom: 1px solid var(--border-color);
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
            /* Keep headers visible while scrolling PO tables */
            position: sticky;
            top: 0;
            background: var(--bg-card);
            z-index: 2;
        }
        
        td {
            padding: 0.75rem;
            border-bottom: 1px solid var(--border-color);
        }
        
        tr:hover { background: rgba(255, 255, 255, 0.02); }
        
        .po-num {
            font-family: 'JetBrains Mono', monospace;
            color: var(--accent-blue);
        }
        
        .badge {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        
        .badge.green { background: rgba(34, 197, 94, 0.2); color: var(--accent-green); }
        .badge.red { background: rgba(239, 68, 68, 0.2); color: var(--accent-red); }
        .badge.orange { background: rgba(249, 115, 22, 0.2); color: var(--accent-orange); }
        .badge.yellow { background: rgba(234, 179, 8, 0.2); color: var(--accent-yellow); }
        
        .scroll-table {
            max-height: 500px;
            overflow-y: auto;
        }
        
        .scroll-table::-webkit-scrollbar { width: 8px; }
        .scroll-table::-webkit-scrollbar-track { background: var(--bg-secondary); border-radius: 4px; }
        .scroll-table::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 4px; }
        
        .chart-container {
            position: relative;
            height: 300px;
            margin-bottom: 1rem;
        }
        
        .aging-bar {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.5rem;
        }
        
        .aging-label {
            width: 100px;
            font-size: 0.75rem;
            color: var(--text-secondary);
        }
        
        .aging-track {
            flex: 1;
            height: 24px;
            background: var(--bg-secondary);
            border-radius: 4px;
            overflow: hidden;
        }
        
        .aging-fill {
            height: 100%;
            display: flex;
            align-items: center;
            padding-left: 0.5rem;
            font-size: 0.75rem;
            font-weight: 600;
            color: white;
            transition: width 0.5s ease;
        }
        
        .aging-fill.green { background: var(--accent-green); }
        .aging-fill.yellow { background: var(--accent-yellow); }
        .aging-fill.orange { background: var(--accent-orange); }
        .aging-fill.red { background: var(--accent-red); }
        
        @media (max-width: 1200px) {
            .kpi-grid { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Navigation -->
        <div class="nav-tabs">
            <a href="/" class="nav-tab">📦 Shortage Dashboard</a>
            <a href="/po-management" class="nav-tab active">📋 PO Management</a>
            <a href="/inventory-health" class="nav-tab">📊 Inventory Health</a>
            <a href="/bom-compare" class="nav-tab">🔍 BOM Comparison</a>
        </div>
        
        <header>
            <div class="logo">
                <div class="logo-icon">📋</div>
                <div>
                    <h1>Purchase Order Management</h1>
                    <div class="subtitle">Monitor and manage all purchase orders</div>
                </div>
            </div>
            <div style="display: flex; align-items: center; gap: 1.5rem;">
                <div class="timestamp">Last updated: {{ timestamp }}</div>
                <button class="refresh-btn" onclick="location.reload()">↻ Refresh</button>
            </div>
        </header>
        
        <!-- KPI Cards -->
        <div class="kpi-grid">
            <div class="kpi-card blue">
                <div class="kpi-label">Total Open POs</div>
                <div class="kpi-value">{{ total_pos }}</div>
                <div class="kpi-subtext">{{ total_po_value|int }} total value</div>
            </div>
            <div class="kpi-card red">
                <div class="kpi-label">Overdue POs</div>
                <div class="kpi-value">{{ overdue_count }}</div>
                <div class="kpi-subtext">{{ overdue_value|int }} value overdue</div>
            </div>
            <div class="kpi-card orange">
                <div class="kpi-label">Avg PO Age</div>
                <div class="kpi-value">{{ avg_age_days|int }}</div>
                <div class="kpi-subtext">days</div>
            </div>
            <div class="kpi-card green">
                <div class="kpi-label">Top Vendors</div>
                <div class="kpi-value">{{ top_vendor_count }}</div>
                <div class="kpi-subtext">Active vendors</div>
            </div>
        </div>
        
        <!-- PO Aging Chart -->
        <div class="section">
            <div class="section-title">
                <span>📊</span> PO Aging Analysis
            </div>
            <div class="chart-container">
                <canvas id="agingChart"></canvas>
            </div>
        </div>
        
        <!-- Overdue POs -->
        <div class="section">
            <div class="section-title">
                <span>⚠️</span> Overdue Purchase Orders ({{ overdue_count }})
            </div>
            <div class="scroll-table">
                <table>
                    <thead>
                        <tr>
                            <th>PO Number</th>
                            <th>Vendor</th>
                            <th>Date Issued</th>
                            <th>Due Date</th>
                            <th>Days Overdue</th>
                            <th>Value</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for po in overdue_pos %}
                        <tr>
                            <td class="po-num">{{ po.po_num }}</td>
                            <td>{{ po.vendor_name }}</td>
                            <td>{{ po.date_issued.strftime('%Y-%m-%d') if po.date_issued else '-' }}</td>
                            <td>{{ po.earliest_due_date.strftime('%Y-%m-%d') if po.earliest_due_date else '-' }}</td>
                            <td><span class="badge red">{{ po.days_overdue }}</span></td>
                            <td>${{ "%.2f"|format(po.total_value) }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- All Open POs -->
        <div class="section">
            <div class="section-title">
                <span>📋</span> All Open Purchase Orders ({{ total_pos }})
            </div>
            <div class="scroll-table">
                <table>
                    <thead>
                        <tr>
                            <th>PO Number</th>
                            <th>Vendor</th>
                            <th>Buyer</th>
                            <th>Status</th>
                            <th>Date Created</th>
                            <th>Date Issued</th>
                            <th>Due Date</th>
                            <th>Line Items</th>
                            <th>Open Qty</th>
                            <th>Total Value</th>
                            <th>Fulfilled %</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for po in po_list %}
                        <tr>
                            <td class="po-num">{{ po.po_num }}</td>
                            <td>{{ po.vendor_name }}</td>
                            <td>{{ po.buyer_name or '-' }}</td>
                            <td><span class="badge orange">{{ po.status }}</span></td>
                            <td>{{ po.date_created.strftime('%Y-%m-%d') if po.date_created else '-' }}</td>
                            <td>{{ po.date_issued.strftime('%Y-%m-%d') if po.date_issued else '-' }}</td>
                            <td>{{ po.earliest_scheduled_date.strftime('%Y-%m-%d') if po.earliest_scheduled_date else '-' }}</td>
                            <td>{{ po.line_count }}</td>
                            <td>{{ po.open_qty|int if po.open_qty else 0 }}</td>
                            <td>${{ "%.2f"|format(po.total_cost or 0) }}</td>
                            <td>
                                {% set fulfilled_pct = ((po.fulfilled_cost or 0) / (po.total_cost or 1) * 100) if po.total_cost else 0 %}
                                <span class="badge {% if fulfilled_pct >= 90 %}green{% elif fulfilled_pct >= 50 %}yellow{% else %}orange{% endif %}">
                                    {{ "%.0f"|format(fulfilled_pct) }}%
                                </span>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Vendor Scorecard -->
        <div class="section">
            <div class="section-title" style="justify-content: space-between; align-items: center;">
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <span>🏆</span> Vendor Scorecard
                </div>
                <div style="display: flex; gap: 1rem; align-items: center;">
                    <label style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; color: var(--text-secondary);">
                        From:
                        <input type="date" id="startDate" value="{{ request.args.get('start_date', '') }}" 
                               style="background: var(--bg-secondary); border: 1px solid var(--border-color); 
                                      color: var(--text-primary); padding: 0.5rem; border-radius: 6px; 
                                      font-family: inherit;">
                    </label>
                    <label style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; color: var(--text-secondary);">
                        To:
                        <input type="date" id="endDate" value="{{ request.args.get('end_date', '') }}" 
                               style="background: var(--bg-secondary); border: 1px solid var(--border-color); 
                                      color: var(--text-primary); padding: 0.5rem; border-radius: 6px; 
                                      font-family: inherit;">
                    </label>
                    <button onclick="applyDateFilter()" 
                            style="background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple)); 
                                   color: white; border: none; padding: 0.5rem 1rem; border-radius: 6px; 
                                   cursor: pointer; font-family: inherit; font-weight: 600;">
                        Apply Filter
                    </button>
                    <button onclick="clearDateFilter()" 
                            style="background: var(--bg-secondary); color: var(--text-primary); 
                                   border: 1px solid var(--border-color); padding: 0.5rem 1rem; 
                                   border-radius: 6px; cursor: pointer; font-family: inherit;">
                        Clear
                    </button>
                </div>
            </div>
            <div class="scroll-table">
                <table>
                    <thead>
                        <tr>
                            <th>Vendor</th>
                            <th>Total POs</th>
                            <th>Total Value</th>
                            <th>Completed</th>
                            <th>On-Time</th>
                            <th>Late</th>
                            <th>On-Time Rate</th>
                            <th>Fulfillment Rate</th>
                            <th>Avg Days</th>
                            <th>Avg Days Late</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for vendor in vendor_performance %}
                        <tr>
                            <td><strong>{{ vendor.vendor_name }}</strong></td>
                            <td>{{ vendor.total_pos }}</td>
                            <td>${{ "%.2f"|format(vendor.total_value) }}</td>
                            <td>{{ vendor.completed_pos }}</td>
                            <td style="color: var(--accent-green);">{{ vendor.on_time_pos }}</td>
                            <td style="color: var(--accent-red);">{{ vendor.late_pos }}</td>
                            <td>
                                <span style="color: {% if vendor.on_time_rate >= 90 %}var(--accent-green){% elif vendor.on_time_rate >= 70 %}var(--accent-yellow){% else %}var(--accent-red){% endif %};">
                                    {{ "%.1f"|format(vendor.on_time_rate) }}%
                                </span>
                            </td>
                            <td>
                                <span style="color: {% if vendor.fulfillment_rate >= 90 %}var(--accent-green){% elif vendor.fulfillment_rate >= 70 %}var(--accent-yellow){% else %}var(--accent-red){% endif %};">
                                    {{ "%.1f"|format(vendor.fulfillment_rate) }}%
                                </span>
                            </td>
                            <td>{{ "%.1f"|format(vendor.avg_fulfillment_days) if vendor.avg_fulfillment_days else '-' }} days</td>
                            <td style="color: {% if vendor.avg_days_late and vendor.avg_days_late > 0 %}var(--accent-red){% else %}var(--text-secondary){% endif %};">
                                {{ "%.1f"|format(vendor.avg_days_late) if vendor.avg_days_late else '-' }} days
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    
    <script>
        Chart.defaults.color = '#94a3b8';
        Chart.defaults.borderColor = '#2d3748';
        
        // PO Aging Chart
        const agingCtx = document.getElementById('agingChart');
        if (agingCtx) {
            const agingData = {
                labels: [{% for age in po_aging %}'{{ age.bucket }}'{% if not loop.last %},{% endif %}{% endfor %}],
                datasets: [{
                    label: 'Number of POs',
                    data: [{% for age in po_aging %}{{ age.po_count }}{% if not loop.last %},{% endif %}{% endfor %}],
                    backgroundColor: [
                        'rgba(34, 197, 94, 0.2)',
                        'rgba(234, 179, 8, 0.2)',
                        'rgba(249, 115, 22, 0.2)',
                        'rgba(239, 68, 68, 0.2)'
                    ],
                    borderColor: [
                        'rgb(34, 197, 94)',
                        'rgb(234, 179, 8)',
                        'rgb(249, 115, 22)',
                        'rgb(239, 68, 68)'
                    ],
                    borderWidth: 2
                }]
            };
            
            new Chart(agingCtx, {
                type: 'bar',
                data: agingData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        title: { display: false }
                    },
                    scales: {
                        y: { beginAtZero: true, grid: { color: 'rgba(45, 55, 72, 0.3)' } },
                        x: { grid: { color: 'rgba(45, 55, 72, 0.3)' } }
                    }
                }
            });
        }
        
        // Date filter functions
        function applyDateFilter() {
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;
            
            let url = window.location.pathname;
            const params = new URLSearchParams();
            
            if (startDate) {
                params.append('start_date', startDate);
            }
            if (endDate) {
                params.append('end_date', endDate);
            }
            
            if (params.toString()) {
                url += '?' + params.toString();
            }
            
            window.location.href = url;
        }
        
        function clearDateFilter() {
            document.getElementById('startDate').value = '';
            document.getElementById('endDate').value = '';
            window.location.href = window.location.pathname;
        }
        
        // Allow Enter key to apply filter
        document.addEventListener('DOMContentLoaded', function() {
            const startDateInput = document.getElementById('startDate');
            const endDateInput = document.getElementById('endDate');
            
            if (startDateInput) {
                startDateInput.addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') {
                        applyDateFilter();
                    }
                });
            }
            
            if (endDateInput) {
                endDateInput.addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') {
                        applyDateFilter();
                    }
                });
            }
        });
    </script>
</body>
</html>
'''

@app.route('/po-management')
def po_management():
    """Purchase Order Management Dashboard"""
    from flask import request
    
    # Get date filter parameters
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    
    po_list = get_po_summary()
    po_aging = get_po_aging()
    vendor_perf = get_vendor_performance(start_date=start_date, end_date=end_date)
    overdue = get_overdue_pos()
    
    # Calculate KPIs
    total_pos = len(po_list)
    total_po_value = sum(po[15] or 0 for po in po_list)  # total_cost (index 15)
    overdue_count = len(overdue)
    overdue_value = sum(po['total_value'] for po in overdue)
    
    # Calculate average age
    from datetime import datetime, date
    total_age_days = 0
    count = 0
    for po in po_list:
        date_ref = po[3] if po[3] else po[2]  # dateIssued (3) or dateCreated (2)
        if date_ref:
            age = (date.today() - date_ref.date()).days if isinstance(date_ref, datetime) else (date.today() - date_ref).days
            total_age_days += age
            count += 1
    avg_age_days = total_age_days / count if count > 0 else 0
    
    # Format PO list for template
    formatted_pos = []
    for po in po_list:
        formatted_pos.append({
            'po_num': po[1],  # po.num
            'vendor_name': po[7],  # vendor_name
            'buyer_name': po[11],  # buyer_name
            'status': po[9],  # status
            'date_created': po[2],  # dateCreated
            'date_issued': po[3],  # dateIssued
            'earliest_scheduled_date': po[17],  # earliest_scheduled_date
            'line_count': po[13],  # line_count
            'open_qty': po[14],  # open_qty
            'total_cost': po[15],  # total_cost
            'fulfilled_cost': po[16]  # fulfilled_cost
        })
    
    return render_template_string(PO_DASHBOARD_TEMPLATE,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        total_pos=total_pos,
        total_po_value=total_po_value,
        overdue_count=overdue_count,
        overdue_value=overdue_value,
        avg_age_days=avg_age_days,
        top_vendor_count=len(vendor_perf),
        po_list=formatted_pos,
        po_aging=po_aging,
        overdue_pos=overdue,
        vendor_performance=vendor_perf,
        request=request
    )

# ================================================================================
# INVENTORY HEALTH ROUTES
# ================================================================================

INVENTORY_HEALTH_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Inventory Health Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        :root {
            --bg-primary: #0a0e17;
            --bg-secondary: #111827;
            --bg-card: #1a2234;
            --text-primary: #f0f4f8;
            --text-secondary: #94a3b8;
            --accent-red: #ef4444;
            --accent-orange: #f97316;
            --accent-yellow: #eab308;
            --accent-green: #22c55e;
            --accent-blue: #3b82f6;
            --accent-purple: #8b5cf6;
            --border-color: #2d3748;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Space Grotesk', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            background-image: 
                radial-gradient(ellipse at top left, rgba(59, 130, 246, 0.1) 0%, transparent 50%),
                radial-gradient(ellipse at bottom right, rgba(139, 92, 246, 0.1) 0%, transparent 50%);
        }
        
        .container { max-width: 1800px; margin: 0 auto; padding: 2rem; }
        
        .nav-tabs {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1rem;
        }
        
        .nav-tab {
            padding: 0.75rem 1.5rem;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px 8px 0 0;
            color: var(--text-secondary);
            text-decoration: none;
            font-weight: 500;
            transition: all 0.2s;
        }
        
        .nav-tab:hover { background: var(--bg-card); color: var(--text-primary); }
        .nav-tab.active { 
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple)); 
            color: white; 
            border-color: transparent;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
        }
        
        .logo { display: flex; align-items: center; gap: 1rem; }
        
        .logo-icon {
            width: 48px; height: 48px;
            background: linear-gradient(135deg, var(--accent-green), var(--accent-blue));
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.5rem;
        }
        
        h1 {
            font-size: 1.75rem;
            font-weight: 700;
            background: linear-gradient(90deg, var(--text-primary), var(--accent-green));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .subtitle { color: var(--text-secondary); font-size: 0.875rem; }
        
        .timestamp {
            color: var(--text-secondary);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.875rem;
        }
        
        .refresh-btn {
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            color: white;
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            cursor: pointer;
            font-family: inherit;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .refresh-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 20px rgba(59, 130, 246, 0.4);
        }
        
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        .kpi-card {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 1.5rem;
            border: 1px solid var(--border-color);
            position: relative;
            overflow: hidden;
        }
        
        .kpi-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
        }
        
        .kpi-card.blue::before { background: var(--accent-blue); }
        .kpi-card.green::before { background: var(--accent-green); }
        .kpi-card.orange::before { background: var(--accent-orange); }
        .kpi-card.red::before { background: var(--accent-red); }
        .kpi-card.purple::before { background: var(--accent-purple); }
        .kpi-card.yellow::before { background: var(--accent-yellow); }
        
        .kpi-label {
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }
        
        .kpi-value {
            font-size: 2rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }
        
        .kpi-card.blue .kpi-value { color: var(--accent-blue); }
        .kpi-card.green .kpi-value { color: var(--accent-green); }
        .kpi-card.orange .kpi-value { color: var(--accent-orange); }
        .kpi-card.red .kpi-value { color: var(--accent-red); }
        .kpi-card.purple .kpi-value { color: var(--accent-purple); }
        .kpi-card.yellow .kpi-value { color: var(--accent-yellow); }
        
        .kpi-subtext {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 0.25rem;
        }
        
        .section {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 1.5rem;
            border: 1px solid var(--border-color);
            margin-bottom: 1.5rem;
        }
        
        .section-title {
            font-size: 1.125rem;
            font-weight: 600;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.875rem;
        }
        
        th {
            text-align: left;
            padding: 0.75rem;
            color: var(--text-secondary);
            font-weight: 500;
            border-bottom: 1px solid var(--border-color);
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
        }
        
        td {
            padding: 0.75rem;
            border-bottom: 1px solid var(--border-color);
        }
        
        tr:hover { background: rgba(255, 255, 255, 0.02); }
        
        .part-num {
            font-family: 'JetBrains Mono', monospace;
            color: var(--accent-blue);
        }
        
        .badge {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        
        .badge.green { background: rgba(34, 197, 94, 0.2); color: var(--accent-green); }
        .badge.red { background: rgba(239, 68, 68, 0.2); color: var(--accent-red); }
        .badge.orange { background: rgba(249, 115, 22, 0.2); color: var(--accent-orange); }
        .badge.yellow { background: rgba(234, 179, 8, 0.2); color: var(--accent-yellow); }
        .badge.purple { background: rgba(139, 92, 246, 0.2); color: var(--accent-purple); }
        
        .scroll-table {
            max-height: 500px;
            overflow-y: auto;
        }
        
        .scroll-table::-webkit-scrollbar { width: 8px; }
        .scroll-table::-webkit-scrollbar-track { background: var(--bg-secondary); border-radius: 4px; }
        .scroll-table::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 4px; }
        
        @media (max-width: 1200px) {
            .kpi-grid { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Navigation -->
        <div class="nav-tabs">
            <a href="/" class="nav-tab">📦 Shortage Dashboard</a>
            <a href="/po-management" class="nav-tab">📋 PO Management</a>
            <a href="/inventory-health" class="nav-tab active">📊 Inventory Health</a>
            <a href="/bom-compare" class="nav-tab">🔍 BOM Comparison</a>
        </div>
        
        <header>
            <div class="logo">
                <div class="logo-icon">📊</div>
                <div>
                    <h1>Inventory Health Dashboard</h1>
                    <div class="subtitle">Monitor inventory health and identify optimization opportunities</div>
                </div>
            </div>
            <div style="display: flex; align-items: center; gap: 1.5rem;">
                <div class="timestamp">Last updated: {{ timestamp }}</div>
                <button class="refresh-btn" onclick="location.reload()">↻ Refresh</button>
            </div>
        </header>
        
        <!-- KPI Cards -->
        <div class="kpi-grid">
            <div class="kpi-card blue">
                <div class="kpi-label">Total Active Parts</div>
                <div class="kpi-value">{{ summary.total_parts }}</div>
                <div class="kpi-subtext">{{ summary.parts_with_stock }} with stock</div>
            </div>
            <div class="kpi-card green">
                <div class="kpi-label">Total Inventory Value</div>
                <div class="kpi-value">${{ "%.0f"|format(summary.total_inventory_value / 1000) }}K</div>
                <div class="kpi-subtext">Full value: ${{ "%.2f"|format(summary.total_inventory_value) }}</div>
            </div>
            <div class="kpi-card orange">
                <div class="kpi-label">Zero Stock Parts</div>
                <div class="kpi-value">{{ summary.zero_stock_parts }}</div>
                <div class="kpi-subtext">Active parts with no stock</div>
            </div>
            <div class="kpi-card purple">
                <div class="kpi-label">Slow Moving (365d)</div>
                <div class="kpi-value">{{ slow_moving|length }}</div>
                <div class="kpi-subtext">Parts with no movement</div>
            </div>
            <div class="kpi-card red">
                <div class="kpi-label">Excess Inventory</div>
                <div class="kpi-value">{{ excess|length }}</div>
                <div class="kpi-subtext">Parts over max levels</div>
            </div>
            <div class="kpi-card yellow">
                <div class="kpi-label">High Turnover Parts</div>
                <div class="kpi-value">{{ turnover|length }}</div>
                <div class="kpi-subtext">Active in last 90 days</div>
            </div>
        </div>
        
        <!-- Zero Stock Active Parts -->
        <div class="section">
            <div class="section-title">
                <span>⚠️</span> Zero Stock Active Parts ({{ zero_stock|length }})
            </div>
            <div class="scroll-table">
                <table>
                    <thead>
                        <tr>
                            <th>Part Number</th>
                            <th>Description</th>
                            <th>Type</th>
                            <th>Open SO Count</th>
                            <th>Open WO Count</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for part in zero_stock %}
                        <tr>
                            <td class="part-num">{{ part.part_num }}</td>
                            <td>{{ part.description[:40] }}</td>
                            <td><span class="badge {% if part.has_bom %}purple{% else %}blue{% endif %}">{% if part.has_bom %}Manufactured{% else %}Purchased{% endif %}</span></td>
                            <td>{{ part.open_so_count }}</td>
                            <td>{{ part.open_wo_count }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Slow Moving Inventory -->
        <div class="section">
            <div class="section-title">
                <span>🐌</span> Slow Moving Inventory (No movement in 365+ days) - Top 100 by Value
            </div>
            <div class="scroll-table">
                <table>
                    <thead>
                        <tr>
                            <th>Part Number</th>
                            <th>Description</th>
                            <th>QOH</th>
                            <th>Inventory Value</th>
                            <th>Last Movement Date</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for part in slow_moving %}
                        <tr>
                            <td class="part-num">{{ part.part_num }}</td>
                            <td>{{ part.description[:40] }}</td>
                            <td>{{ part.qoh|int }}</td>
                            <td>${{ "%.2f"|format(part.inventory_value) }}</td>
                            <td>{{ part.last_movement_date.strftime('%Y-%m-%d') if part.last_movement_date else 'Never' }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Excess Inventory -->
        <div class="section">
            <div class="section-title">
                <span>📦</span> High Value Inventory - Top 100 by Value
            </div>
            <div class="scroll-table">
                <table>
                    <thead>
                        <tr>
                            <th>Part Number</th>
                            <th>Description</th>
                            <th>Current QOH</th>
                            <th>Inventory Value</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for part in excess %}
                        <tr>
                            <td class="part-num">{{ part.part_num }}</td>
                            <td>{{ part.description[:40] }}</td>
                            <td><span class="badge orange">{{ part.current_qoh|int }}</span></td>
                            <td>${{ "%.2f"|format(part.inventory_value) }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- High Turnover Parts -->
        <div class="section">
            <div class="section-title">
                <span>⚡</span> High Turnover Parts (Active in last 90 days) - Top 50
            </div>
            <div class="scroll-table">
                <table>
                    <thead>
                        <tr>
                            <th>Part Number</th>
                            <th>Description</th>
                            <th>Avg QOH</th>
                            <th>Transactions (90d)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for part in turnover %}
                        <tr>
                            <td class="part-num">{{ part.part_num }}</td>
                            <td>{{ part.description[:40] }}</td>
                            <td>{{ part.avg_qoh|int }}</td>
                            <td><span class="badge green">{{ part.transactions_90d }}</span></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
'''

@app.route('/inventory-health')
def inventory_health():
    """Inventory Health Dashboard"""
    summary = get_inventory_health_summary()
    slow_moving = get_slow_moving_inventory()
    excess = get_excess_inventory()
    zero_stock = get_zero_stock_active_parts()
    turnover = get_inventory_turnover()
    
    return render_template_string(INVENTORY_HEALTH_TEMPLATE,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        summary=summary,
        slow_moving=slow_moving,
        excess=excess,
        zero_stock=zero_stock,
        turnover=turnover
    )

if __name__ == '__main__':
    print("=" * 60)
    print("  SUPPLY CHAIN SHORTAGE KPI WEB DASHBOARD")
    print("=" * 60)
    print(f"  Starting server...")
    print(f"  Access at: http://localhost:5555")
    print(f"  Or from other computers: http://<this-pc-ip>:5555")
    print("=" * 60)
    print("  Press Ctrl+C to stop the server")
    print("=" * 60)
    
    # Run on all interfaces so other computers can access
    app.run(host='0.0.0.0', port=5555, debug=False)
