"""
================================================================================
SUPPLY CHAIN SHORTAGE KPI DASHBOARD
================================================================================
This script analyzes picking shortages and distinguishes between:
1. TRUE MATERIAL SHORTAGES - No inventory available anywhere
2. WIP SHORTAGES - Material exists but tied to Work Orders (not a true shortage)

Provides weekly, monthly, and running total KPIs.
================================================================================
"""

import pymysql
from datetime import datetime, timedelta
from collections import defaultdict

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
    """Get current shortage breakdown"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        pi.id as pickitem_id,
        p.id as part_id,
        p.num as part_num,
        p.description,
        pk.id as pick_id,
        COALESCE(ot.name, 'N/A') as order_type,
        -- Qty in available stock locations
        (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         WHERE t.partId = p.id AND t.qty > 0 
         AND l.countedAsAvailable = 1) as available_qoh,
        -- Qty in WIP (Manufacturing locations OR tied to WO)
        (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
         JOIN location l ON t.locationId = l.id 
         WHERE t.partId = p.id AND t.qty > 0 
         AND (l.typeId = 80 OR t.woItemId IS NOT NULL)) as wip_qty,
        -- Total on order (PO)
        (SELECT COALESCE(SUM(poi.qtyToFulfill - poi.qtyFulfilled), 0) 
         FROM poitem poi 
         JOIN po ON poi.poId = po.id 
         WHERE poi.partId = p.id 
         AND po.statusId IN (20, 30, 40)) as on_order_qty,
        -- Qty being manufactured (Finished Good in open MOs: Entered=10, Issued=20, Partial=50)
        (SELECT COALESCE(SUM(moitem.qtyToFulfill - moitem.qtyFulfilled), 0)
         FROM moitem
         JOIN mo ON moitem.moId = mo.id
         WHERE moitem.partId = p.id
         AND moitem.typeId = 10  -- Finished Good
         AND mo.statusId IN (10, 20, 50)  -- Entered, Issued, Partial
         AND moitem.statusId NOT IN (50, 60, 70)) as being_manufactured_qty
    FROM pickitem pi
    JOIN pickitemstatus pis ON pi.statusId = pis.id
    JOIN part p ON pi.partId = p.id
    JOIN pick pk ON pi.pickId = pk.id
    LEFT JOIN ordertype ot ON pi.orderTypeId = ot.id
    WHERE pis.id = 5  -- Short status
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return results

def categorize_shortages(shortages):
    """Categorize shortages into TRUE vs WIP"""
    true_shortages = []
    wip_shortages = []
    other_shortages = []  # Has available stock but still short (committed elsewhere)
    
    for row in shortages:
        pickitem_id, part_id, part_num, desc, pick_id, order_type, available_qoh, wip_qty, on_order, being_mfg_qty = row
        
        # Combined WIP = inventory in WIP locations + qty being manufactured in open MOs
        total_wip = float(wip_qty) + float(being_mfg_qty)
        
        if available_qoh <= 0 and total_wip <= 0:
            # TRUE SHORTAGE: No available stock AND no WIP AND not being manufactured
            true_shortages.append({
                'pickitem_id': pickitem_id,
                'part_id': part_id,
                'part_num': part_num,
                'description': desc,
                'pick_id': pick_id,
                'order_type': order_type,
                'available_qty': available_qoh,
                'wip_qty': wip_qty,
                'being_mfg_qty': being_mfg_qty,
                'on_order_qty': on_order
            })
        elif available_qoh <= 0 and total_wip > 0:
            # WIP SHORTAGE: No available stock BUT has WIP inventory OR being manufactured
            wip_shortages.append({
                'pickitem_id': pickitem_id,
                'part_id': part_id,
                'part_num': part_num,
                'description': desc,
                'pick_id': pick_id,
                'order_type': order_type,
                'available_qty': available_qoh,
                'wip_qty': wip_qty,
                'being_mfg_qty': being_mfg_qty,
                'on_order_qty': on_order
            })
        else:
            other_shortages.append({
                'pickitem_id': pickitem_id,
                'part_id': part_id,
                'part_num': part_num,
                'description': desc,
                'pick_id': pick_id,
                'order_type': order_type,
                'available_qty': available_qoh,
                'wip_qty': wip_qty,
                'being_mfg_qty': being_mfg_qty,
                'on_order_qty': on_order
            })
    
    return true_shortages, wip_shortages, other_shortages

def get_historical_shortages():
    """Get historical shortage data from inventory logs for trending"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get pick items that went short historically (from audit trail or pick history)
    query = '''
    SELECT 
        DATE(pk.dateCreated) as pick_date,
        YEAR(pk.dateCreated) as yr,
        WEEK(pk.dateCreated) as wk,
        MONTH(pk.dateCreated) as mo,
        COUNT(DISTINCT pi.id) as total_short_items,
        COUNT(DISTINCT pi.partId) as unique_parts_short
    FROM pickitem pi
    JOIN pick pk ON pi.pickId = pk.id
    WHERE pi.statusId = 5  -- Short
    AND pk.dateCreated IS NOT NULL
    GROUP BY DATE(pk.dateCreated), YEAR(pk.dateCreated), WEEK(pk.dateCreated), MONTH(pk.dateCreated)
    ORDER BY pick_date DESC
    LIMIT 365
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return results

def get_weekly_kpi():
    """Get weekly shortage KPIs"""
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
    
    return results

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
    
    return results

def get_shortage_aging():
    """Get aging analysis of current shortages"""
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
    
    return results

def print_dashboard():
    """Print the complete KPI dashboard"""
    
    print("=" * 100)
    print("  SUPPLY CHAIN SHORTAGE KPI DASHBOARD")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 100)
    
    # Get current shortages
    shortages = get_current_shortages()
    true_shortages, wip_shortages, other_shortages = categorize_shortages(shortages)
    
    # SUMMARY
    print("\n" + "=" * 100)
    print("  CURRENT SHORTAGE SUMMARY")
    print("=" * 100)
    print(f"\n  Total Short Pick Items:        {len(shortages)}")
    print(f"  +-- TRUE Material Shortages:   {len(true_shortages)} (no inventory anywhere)")
    print(f"  +-- WIP Shortages:             {len(wip_shortages)} (material in WO/WIP)")
    print(f"  +-- Committed Elsewhere:       {len(other_shortages)} (stock exists but committed)")
    
    # Unique parts
    true_parts = len(set(s['part_id'] for s in true_shortages))
    wip_parts = len(set(s['part_id'] for s in wip_shortages))
    other_parts = len(set(s['part_id'] for s in other_shortages))
    
    print(f"\n  Unique Parts Affected:")
    print(f"  +-- TRUE Shortages:            {true_parts} unique parts")
    print(f"  +-- WIP Shortages:             {wip_parts} unique parts")
    print(f"  +-- Committed Elsewhere:       {other_parts} unique parts")
    
    # TRUE SHORTAGES DETAIL
    print("\n" + "-" * 100)
    print("  TRUE MATERIAL SHORTAGES (Action Required)")
    print("-" * 100)
    
    if true_shortages:
        # Group by part
        by_part = defaultdict(list)
        for s in true_shortages:
            by_part[s['part_num']].append(s)
        
        print(f"\n  {'Part Number':<30} {'Description':<45} {'On Order':<10}")
        print("  " + "-" * 90)
        
        for part_num, items in sorted(by_part.items())[:20]:
            desc = items[0]['description'][:45] if items[0]['description'] else ''
            on_order = items[0]['on_order_qty']
            print(f"  {part_num:<30} {desc:<45} {on_order:<10.0f}")
        
        if len(by_part) > 20:
            print(f"\n  ... and {len(by_part) - 20} more parts")
    else:
        print("\n  No true material shortages! [OK]")
    
    # WIP SHORTAGES DETAIL
    print("\n" + "-" * 100)
    print("  WIP SHORTAGES (Waiting on Work Orders or Being Manufactured)")
    print("-" * 100)
    
    if wip_shortages:
        by_part = defaultdict(list)
        for s in wip_shortages:
            by_part[s['part_num']].append(s)
        
        print(f"\n  {'Part Number':<30} {'Description':<30} {'WIP Inv':<10} {'Being Mfg':<10}")
        print("  " + "-" * 85)
        
        for part_num, items in sorted(by_part.items()):
            desc = items[0]['description'][:30] if items[0]['description'] else ''
            wip_qty = float(items[0]['wip_qty'])
            being_mfg = float(items[0]['being_mfg_qty'])
            print(f"  {part_num:<30} {desc:<30} {wip_qty:<10.0f} {being_mfg:<10.0f}")
    else:
        print("\n  No WIP-related shortages!")
    
    # AGING ANALYSIS
    print("\n" + "=" * 100)
    print("  SHORTAGE AGING ANALYSIS")
    print("=" * 100)
    
    aging = get_shortage_aging()
    print(f"\n  {'Age Bucket':<15} {'Short Items':<15} {'Unique Parts':<15}")
    print("  " + "-" * 45)
    
    for row in aging:
        print(f"  {row[0]:<15} {row[1]:<15} {row[2]:<15}")
    
    # WEEKLY KPI
    print("\n" + "=" * 100)
    print("  WEEKLY KPI (Last 12 Weeks)")
    print("=" * 100)
    
    weekly = get_weekly_kpi()
    if weekly:
        print(f"\n  {'Week Start':<15} {'Short Items':<15} {'Unique Parts':<15} {'Affected Picks':<15}")
        print("  " + "-" * 60)
        
        total_items = 0
        total_parts = 0
        for row in weekly:
            yr, wk, week_start, items, parts, picks = row
            total_items += items
            total_parts += parts
            print(f"  {str(week_start):<15} {items:<15} {parts:<15} {picks:<15}")
        
        # Averages
        if len(weekly) > 0:
            avg_items = total_items / len(weekly)
            avg_parts = total_parts / len(weekly)
            print("  " + "-" * 60)
            print(f"  {'WEEKLY AVG':<15} {avg_items:<15.1f} {avg_parts:<15.1f}")
    
    # MONTHLY KPI
    print("\n" + "=" * 100)
    print("  MONTHLY KPI (Last 12 Months)")
    print("=" * 100)
    
    monthly = get_monthly_kpi()
    if monthly:
        print(f"\n  {'Month':<15} {'Short Items':<15} {'Unique Parts':<15} {'Affected Picks':<15}")
        print("  " + "-" * 60)
        
        total_items = 0
        total_parts = 0
        for row in monthly:
            yr, mo, month_label, items, parts, picks = row
            total_items += items
            total_parts += parts
            print(f"  {month_label:<15} {items:<15} {parts:<15} {picks:<15}")
        
        # Running total and averages
        if len(monthly) > 0:
            avg_items = total_items / len(monthly)
            avg_parts = total_parts / len(monthly)
            print("  " + "-" * 60)
            print(f"  {'RUNNING TOTAL':<15} {total_items:<15} {'-':<15}")
            print(f"  {'MONTHLY AVG':<15} {avg_items:<15.1f} {avg_parts:<15.1f}")
    
    # KPI METRICS SUMMARY
    print("\n" + "=" * 100)
    print("  KEY PERFORMANCE INDICATORS")
    print("=" * 100)
    
    total_short = len(shortages)
    true_pct = (len(true_shortages) / total_short * 100) if total_short > 0 else 0
    wip_pct = (len(wip_shortages) / total_short * 100) if total_short > 0 else 0
    
    print(f"""
  +-----------------------------------------------------------------------------+
  |  SHORTAGE BREAKDOWN                                                         |
  +-----------------------------------------------------------------------------+
  |  TRUE Material Shortage Rate:     {true_pct:>6.1f}%  ({len(true_shortages)} items)                     |
  |  WIP Shortage Rate:               {wip_pct:>6.1f}%  ({len(wip_shortages)} items)                        |
  |  Committed Elsewhere Rate:        {100-true_pct-wip_pct:>6.1f}%  ({len(other_shortages)} items)                      |
  +-----------------------------------------------------------------------------+
  
  RECOMMENDATION: Focus on the {len(true_shortages)} TRUE material shortages.
  The {len(wip_shortages)} WIP shortages will resolve when Work Orders complete.
    """)
    
    print("=" * 100)
    print("  END OF REPORT")
    print("=" * 100)

if __name__ == "__main__":
    print_dashboard()
