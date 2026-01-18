-- ================================================================================
-- SUPPLY CHAIN SHORTAGE KPI QUERIES
-- ================================================================================
-- These queries help identify and categorize picking shortages into:
-- 1. TRUE Material Shortages - No inventory available anywhere
-- 2. WIP Shortages - Material exists but tied to Work Orders
-- 3. Committed Shortages - Stock exists but committed to other orders
-- ================================================================================

-- ================================================================================
-- QUERY 1: CURRENT SHORTAGES WITH CATEGORIZATION
-- This is the main query that categorizes all current shortages
-- ================================================================================
SELECT 
    pi.id as pickitem_id,
    p.num as part_num,
    p.description,
    pk.id as pick_id,
    pk.dateCreated as pick_created,
    COALESCE(ot.name, 'N/A') as order_type,
    
    -- Available inventory (in stock, countable locations)
    (SELECT COALESCE(SUM(t.qty), 0) 
     FROM tag t 
     JOIN location l ON t.locationId = l.id 
     WHERE t.partId = p.id AND t.qty > 0 
     AND l.countedAsAvailable = 1) as available_qty,
    
    -- WIP inventory (Manufacturing locations OR tied to WO)
    (SELECT COALESCE(SUM(t.qty), 0) 
     FROM tag t 
     JOIN location l ON t.locationId = l.id 
     WHERE t.partId = p.id AND t.qty > 0 
     AND (l.typeId = 80 OR t.woItemId IS NOT NULL)) as wip_qty,
    
    -- On order quantity (open POs)
    (SELECT COALESCE(SUM(poi.qtyToFulfill - poi.qtyFulfilled), 0) 
     FROM poitem poi 
     JOIN po ON poi.poId = po.id 
     WHERE poi.partId = p.id 
     AND po.statusId IN (20, 30, 40)) as on_order_qty,
    
    -- Shortage category
    CASE 
        WHEN (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
              JOIN location l ON t.locationId = l.id 
              WHERE t.partId = p.id AND t.qty > 0 
              AND l.countedAsAvailable = 1) <= 0 
         AND (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
              JOIN location l ON t.locationId = l.id 
              WHERE t.partId = p.id AND t.qty > 0 
              AND (l.typeId = 80 OR t.woItemId IS NOT NULL)) <= 0 
        THEN 'TRUE_SHORTAGE'
        
        WHEN (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
              JOIN location l ON t.locationId = l.id 
              WHERE t.partId = p.id AND t.qty > 0 
              AND l.countedAsAvailable = 1) <= 0 
         AND (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
              JOIN location l ON t.locationId = l.id 
              WHERE t.partId = p.id AND t.qty > 0 
              AND (l.typeId = 80 OR t.woItemId IS NOT NULL)) > 0 
        THEN 'WIP_SHORTAGE'
        
        ELSE 'COMMITTED_ELSEWHERE'
    END as shortage_category,
    
    -- Aging (days)
    DATEDIFF(CURDATE(), pk.dateCreated) as age_days
    
FROM pickitem pi
JOIN pickitemstatus pis ON pi.statusId = pis.id
JOIN part p ON pi.partId = p.id
JOIN pick pk ON pi.pickId = pk.id
LEFT JOIN ordertype ot ON pi.orderTypeId = ot.id
WHERE pis.id = 5  -- Short status
ORDER BY shortage_category, p.num;


-- ================================================================================
-- QUERY 2: TRUE MATERIAL SHORTAGES ONLY (Action Required)
-- Use this to focus on parts that need purchasing/procurement action
-- ================================================================================
SELECT 
    p.num as part_num,
    p.description,
    COUNT(DISTINCT pi.id) as short_pick_items,
    COUNT(DISTINCT pk.id) as affected_picks,
    MIN(pk.dateCreated) as oldest_shortage_date,
    MAX(DATEDIFF(CURDATE(), pk.dateCreated)) as max_age_days,
    
    -- On order quantity
    (SELECT COALESCE(SUM(poi.qtyToFulfill - poi.qtyFulfilled), 0) 
     FROM poitem poi 
     JOIN po ON poi.poId = po.id 
     WHERE poi.partId = p.id 
     AND po.statusId IN (20, 30, 40)) as on_order_qty,
    
    -- Expected receipt date (earliest open PO)
    (SELECT MIN(poi.dateScheduledFulfillment)
     FROM poitem poi 
     JOIN po ON poi.poId = po.id 
     WHERE poi.partId = p.id 
     AND po.statusId IN (20, 30, 40)
     AND poi.statusId NOT IN (50, 60, 70)) as expected_receipt_date
    
FROM pickitem pi
JOIN pickitemstatus pis ON pi.statusId = pis.id
JOIN part p ON pi.partId = p.id
JOIN pick pk ON pi.pickId = pk.id
WHERE pis.id = 5  -- Short status
  -- TRUE SHORTAGE: No available stock AND no WIP
  AND (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
       JOIN location l ON t.locationId = l.id 
       WHERE t.partId = p.id AND t.qty > 0 
       AND l.countedAsAvailable = 1) <= 0
  AND (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
       JOIN location l ON t.locationId = l.id 
       WHERE t.partId = p.id AND t.qty > 0 
       AND (l.typeId = 80 OR t.woItemId IS NOT NULL)) <= 0
GROUP BY p.id, p.num, p.description
ORDER BY max_age_days DESC, short_pick_items DESC;


-- ================================================================================
-- QUERY 3: WIP SHORTAGES (Waiting on Work Orders)
-- Use this to track shortages waiting for WO completion
-- ================================================================================
SELECT 
    p.num as part_num,
    p.description,
    COUNT(DISTINCT pi.id) as short_pick_items,
    
    -- WIP quantity
    (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
     JOIN location l ON t.locationId = l.id 
     WHERE t.partId = p.id AND t.qty > 0 
     AND (l.typeId = 80 OR t.woItemId IS NOT NULL)) as wip_qty,
    
    -- Related Work Orders
    (SELECT GROUP_CONCAT(DISTINCT wo.num SEPARATOR ', ')
     FROM tag t 
     JOIN woitem wi ON t.woItemId = wi.id
     JOIN wo ON wi.woId = wo.id
     WHERE t.partId = p.id AND t.qty > 0) as related_work_orders
    
FROM pickitem pi
JOIN pickitemstatus pis ON pi.statusId = pis.id
JOIN part p ON pi.partId = p.id
WHERE pis.id = 5  -- Short status
  -- WIP SHORTAGE: No available stock BUT has WIP
  AND (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
       JOIN location l ON t.locationId = l.id 
       WHERE t.partId = p.id AND t.qty > 0 
       AND l.countedAsAvailable = 1) <= 0
  AND (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
       JOIN location l ON t.locationId = l.id 
       WHERE t.partId = p.id AND t.qty > 0 
       AND (l.typeId = 80 OR t.woItemId IS NOT NULL)) > 0
GROUP BY p.id, p.num, p.description
ORDER BY wip_qty DESC;


-- ================================================================================
-- QUERY 4: SHORTAGE SUMMARY BY CATEGORY
-- Quick summary for dashboard
-- ================================================================================
SELECT 
    shortage_category,
    COUNT(*) as pick_items,
    COUNT(DISTINCT part_id) as unique_parts
FROM (
    SELECT 
        pi.id,
        p.id as part_id,
        CASE 
            WHEN (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
                  JOIN location l ON t.locationId = l.id 
                  WHERE t.partId = p.id AND t.qty > 0 
                  AND l.countedAsAvailable = 1) <= 0 
             AND (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
                  JOIN location l ON t.locationId = l.id 
                  WHERE t.partId = p.id AND t.qty > 0 
                  AND (l.typeId = 80 OR t.woItemId IS NOT NULL)) <= 0 
            THEN 'TRUE_SHORTAGE'
            
            WHEN (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
                  JOIN location l ON t.locationId = l.id 
                  WHERE t.partId = p.id AND t.qty > 0 
                  AND l.countedAsAvailable = 1) <= 0 
             AND (SELECT COALESCE(SUM(t.qty), 0) FROM tag t 
                  JOIN location l ON t.locationId = l.id 
                  WHERE t.partId = p.id AND t.qty > 0 
                  AND (l.typeId = 80 OR t.woItemId IS NOT NULL)) > 0 
            THEN 'WIP_SHORTAGE'
            
            ELSE 'COMMITTED_ELSEWHERE'
        END as shortage_category
    FROM pickitem pi
    JOIN part p ON pi.partId = p.id
    WHERE pi.statusId = 5
) categorized
GROUP BY shortage_category
ORDER BY 
    CASE shortage_category 
        WHEN 'TRUE_SHORTAGE' THEN 1 
        WHEN 'WIP_SHORTAGE' THEN 2 
        ELSE 3 
    END;


-- ================================================================================
-- QUERY 5: WEEKLY KPI TREND
-- Track shortages by week for trending
-- ================================================================================
SELECT 
    YEAR(pk.dateCreated) as year,
    WEEK(pk.dateCreated) as week,
    MIN(DATE(pk.dateCreated)) as week_start,
    COUNT(DISTINCT pi.id) as short_pick_items,
    COUNT(DISTINCT pi.partId) as unique_parts_short,
    COUNT(DISTINCT pk.id) as picks_with_shorts
FROM pickitem pi
JOIN pick pk ON pi.pickId = pk.id
WHERE pi.statusId = 5
AND pk.dateCreated >= DATE_SUB(CURDATE(), INTERVAL 12 WEEK)
GROUP BY YEAR(pk.dateCreated), WEEK(pk.dateCreated)
ORDER BY year DESC, week DESC;


-- ================================================================================
-- QUERY 6: MONTHLY KPI TREND
-- Track shortages by month for trending
-- ================================================================================
SELECT 
    YEAR(pk.dateCreated) as year,
    MONTH(pk.dateCreated) as month,
    CONCAT(YEAR(pk.dateCreated), '-', LPAD(MONTH(pk.dateCreated), 2, '0')) as month_label,
    COUNT(DISTINCT pi.id) as short_pick_items,
    COUNT(DISTINCT pi.partId) as unique_parts_short,
    COUNT(DISTINCT pk.id) as picks_with_shorts
FROM pickitem pi
JOIN pick pk ON pi.pickId = pk.id
WHERE pi.statusId = 5
AND pk.dateCreated >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
GROUP BY YEAR(pk.dateCreated), MONTH(pk.dateCreated)
ORDER BY year DESC, month DESC;


-- ================================================================================
-- QUERY 7: SHORTAGE AGING ANALYSIS
-- Analyze how long shortages have been outstanding
-- ================================================================================
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
    END;


-- ================================================================================
-- QUERY 8: RUNNING TOTALS AND AVERAGES
-- Calculate running totals for KPI tracking
-- ================================================================================
WITH weekly_data AS (
    SELECT 
        YEAR(pk.dateCreated) as yr,
        WEEK(pk.dateCreated) as wk,
        COUNT(DISTINCT pi.id) as short_items,
        COUNT(DISTINCT pi.partId) as unique_parts
    FROM pickitem pi
    JOIN pick pk ON pi.pickId = pk.id
    WHERE pi.statusId = 5
    AND pk.dateCreated >= DATE_SUB(CURDATE(), INTERVAL 12 WEEK)
    GROUP BY YEAR(pk.dateCreated), WEEK(pk.dateCreated)
)
SELECT 
    'WEEKLY SUMMARY' as metric_type,
    SUM(short_items) as total_short_items,
    AVG(short_items) as avg_short_items_per_week,
    SUM(unique_parts) as total_unique_parts,
    AVG(unique_parts) as avg_unique_parts_per_week,
    COUNT(*) as weeks_analyzed
FROM weekly_data

UNION ALL

SELECT 
    'MONTHLY SUMMARY',
    SUM(short_items),
    AVG(short_items),
    SUM(unique_parts),
    AVG(unique_parts),
    COUNT(*)
FROM (
    SELECT 
        YEAR(pk.dateCreated) as yr,
        MONTH(pk.dateCreated) as mo,
        COUNT(DISTINCT pi.id) as short_items,
        COUNT(DISTINCT pi.partId) as unique_parts
    FROM pickitem pi
    JOIN pick pk ON pi.pickId = pk.id
    WHERE pi.statusId = 5
    AND pk.dateCreated >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
    GROUP BY YEAR(pk.dateCreated), MONTH(pk.dateCreated)
) monthly_data;


-- ================================================================================
-- QUERY 9: SHORTAGE BY ORDER TYPE
-- See which order types have the most shortages
-- ================================================================================
SELECT 
    COALESCE(ot.name, 'N/A') as order_type,
    COUNT(DISTINCT pi.id) as short_items,
    COUNT(DISTINCT pi.partId) as unique_parts,
    COUNT(DISTINCT pk.id) as affected_picks
FROM pickitem pi
JOIN pick pk ON pi.pickId = pk.id
LEFT JOIN ordertype ot ON pi.orderTypeId = ot.id
WHERE pi.statusId = 5
GROUP BY ot.id, ot.name
ORDER BY short_items DESC;


-- ================================================================================
-- QUERY 10: PARTS WITH RECURRING SHORTAGES
-- Identify parts that frequently go short (repeat offenders)
-- ================================================================================
SELECT 
    p.num as part_num,
    p.description,
    COUNT(DISTINCT pi.id) as total_short_occurrences,
    COUNT(DISTINCT pk.id) as affected_picks,
    MIN(pk.dateCreated) as first_shortage_date,
    MAX(pk.dateCreated) as latest_shortage_date,
    DATEDIFF(MAX(pk.dateCreated), MIN(pk.dateCreated)) as shortage_span_days
FROM pickitem pi
JOIN pick pk ON pi.pickId = pk.id
JOIN part p ON pi.partId = p.id
WHERE pi.statusId = 5
GROUP BY p.id, p.num, p.description
HAVING COUNT(DISTINCT pi.id) > 1
ORDER BY total_short_occurrences DESC
LIMIT 25;


-- ================================================================================
-- KEY DEFINITIONS
-- ================================================================================
-- Short Status (pickitemstatus.id = 5): Items marked as short in picking
-- 
-- TRUE Material Shortage:
--   - No inventory in any "countedAsAvailable" location
--   - No inventory in WIP/Manufacturing locations
--   - No inventory tied to Work Orders
--   ACTION: Create PO or expedite existing orders
--
-- WIP Shortage:
--   - No available inventory
--   - BUT inventory exists in Manufacturing locations OR tied to WO
--   ACTION: Track related WO completion - no procurement needed
--
-- Committed Elsewhere:
--   - Available inventory exists
--   - But it's committed to other orders
--   ACTION: May need to reprioritize or increase quantities
--
-- Location Types:
--   10 = Stock
--   80 = Manufacturing (WIP)
-- ================================================================================
