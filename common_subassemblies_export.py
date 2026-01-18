import pymysql
import csv
from collections import defaultdict
from datetime import datetime

conn = pymysql.connect(
    host='451-srv-fbwl01',
    port=3306,
    user='ReadUser',
    password='Metrohm2026!',
    database='MetrohmSpectro'
)

cursor = conn.cursor()

part1 = '29540011'
part2 = '29540031'

def get_bom_components(part_num, level=0, parent_path=""):
    """Recursively get all BOM components for a part"""
    components = []
    
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
        ORDER BY comp.num
    ''', (part_num,))
    
    results = cursor.fetchall()
    
    for row in results:
        part_id, comp_num, desc, qty, uom, item_type, has_bom = row
        
        if comp_num == part_num:
            continue
            
        path = f"{parent_path}/{comp_num}" if parent_path else comp_num
        
        components.append({
            'part_id': part_id,
            'part_num': comp_num,
            'description': desc,
            'quantity': qty,
            'uom': uom,
            'item_type': item_type,
            'level': level,
            'path': path,
            'has_bom': has_bom is not None
        })
        
        if has_bom and level < 5:
            sub_components = get_bom_components(comp_num, level + 1, path)
            components.extend(sub_components)
    
    return components

def get_inventory(part_id):
    """Get inventory quantities for a part"""
    cursor.execute('''
        SELECT COALESCE(SUM(t.qty), 0) 
        FROM tag t 
        JOIN location l ON t.locationId = l.id 
        WHERE t.partId = %s AND t.qty > 0 
        AND l.countedAsAvailable = 1
    ''', (part_id,))
    available_qty = cursor.fetchone()[0] or 0
    
    cursor.execute('''
        SELECT COALESCE(SUM(t.qtyCommitted), 0) 
        FROM tag t 
        JOIN location l ON t.locationId = l.id 
        WHERE t.partId = %s
        AND l.countedAsAvailable = 1
    ''', (part_id,))
    committed_qty = cursor.fetchone()[0] or 0
    
    cursor.execute('''
        SELECT COALESCE(SUM(t.qty), 0) 
        FROM tag t 
        JOIN location l ON t.locationId = l.id 
        WHERE t.partId = %s AND t.qty > 0 
        AND (l.typeId = 80 OR t.woItemId IS NOT NULL)
    ''', (part_id,))
    wip_qty = cursor.fetchone()[0] or 0
    
    # Total inventory (all locations)
    cursor.execute('''
        SELECT COALESCE(SUM(t.qty), 0) 
        FROM tag t 
        WHERE t.partId = %s AND t.qty > 0
    ''', (part_id,))
    total_qty = cursor.fetchone()[0] or 0
    
    return float(available_qty), float(committed_qty), float(wip_qty), float(total_qty)

print(f'Generating export for common sub-assemblies between {part1} and {part2}...')
print('Exploding BOMs...')

part1_all_components = get_bom_components(part1)
part2_all_components = get_bom_components(part2)

print(f'{part1}: {len(part1_all_components)} components')
print(f'{part2}: {len(part2_all_components)} components')

# Create lookup by part_num
part1_by_num = {}
for c in part1_all_components:
    if c['part_num'] not in part1_by_num:
        part1_by_num[c['part_num']] = c

part2_by_num = {}
for c in part2_all_components:
    if c['part_num'] not in part2_by_num:
        part2_by_num[c['part_num']] = c

# Find common parts
common_nums = set(part1_by_num.keys()) & set(part2_by_num.keys())
unique_to_1 = set(part1_by_num.keys()) - common_nums
unique_to_2 = set(part2_by_num.keys()) - common_nums

print(f'Common: {len(common_nums)}, Unique to {part1}: {len(unique_to_1)}, Unique to {part2}: {len(unique_to_2)}')
print('Fetching inventory data...')

# Build results for common components
common_results = []
for part_num in common_nums:
    c1 = part1_by_num[part_num]
    c2 = part2_by_num[part_num]
    
    available, committed, wip, total = get_inventory(c1['part_id'])
    net_available = available - committed
    
    # Determine stock status
    if net_available > 0:
        stock_status = 'In Stock'
    elif wip > 0:
        stock_status = 'WIP Only'
    else:
        stock_status = 'Shortage'
    
    common_results.append({
        'Part Number': part_num,
        'Description': c1['description'] or '',
        'BOM Level (in ' + part1 + ')': c1['level'],
        'BOM Level (in ' + part2 + ')': c2['level'],
        'Qty per ' + part1: float(c1['quantity']),
        'Qty per ' + part2: float(c2['quantity']),
        'UOM': c1['uom'],
        'Has Sub-BOM': 'Yes' if c1['has_bom'] else 'No',
        'Available Qty': available,
        'Committed Qty': committed,
        'Net Available': net_available,
        'WIP Qty': wip,
        'Total Inventory': total,
        'Stock Status': stock_status,
        'Component Type': 'Common'
    })

# Build results for unique components
unique_results_1 = []
for part_num in unique_to_1:
    c = part1_by_num[part_num]
    available, committed, wip, total = get_inventory(c['part_id'])
    net_available = available - committed
    
    if net_available > 0:
        stock_status = 'In Stock'
    elif wip > 0:
        stock_status = 'WIP Only'
    else:
        stock_status = 'Shortage'
    
    unique_results_1.append({
        'Part Number': part_num,
        'Description': c['description'] or '',
        'BOM Level (in ' + part1 + ')': c['level'],
        'BOM Level (in ' + part2 + ')': 'N/A',
        'Qty per ' + part1: float(c['quantity']),
        'Qty per ' + part2: 0,
        'UOM': c['uom'],
        'Has Sub-BOM': 'Yes' if c['has_bom'] else 'No',
        'Available Qty': available,
        'Committed Qty': committed,
        'Net Available': net_available,
        'WIP Qty': wip,
        'Total Inventory': total,
        'Stock Status': stock_status,
        'Component Type': f'Unique to {part1}'
    })

unique_results_2 = []
for part_num in unique_to_2:
    c = part2_by_num[part_num]
    available, committed, wip, total = get_inventory(c['part_id'])
    net_available = available - committed
    
    if net_available > 0:
        stock_status = 'In Stock'
    elif wip > 0:
        stock_status = 'WIP Only'
    else:
        stock_status = 'Shortage'
    
    unique_results_2.append({
        'Part Number': part_num,
        'Description': c['description'] or '',
        'BOM Level (in ' + part1 + ')': 'N/A',
        'BOM Level (in ' + part2 + ')': c['level'],
        'Qty per ' + part1: 0,
        'Qty per ' + part2: float(c['quantity']),
        'UOM': c['uom'],
        'Has Sub-BOM': 'Yes' if c['has_bom'] else 'No',
        'Available Qty': available,
        'Committed Qty': committed,
        'Net Available': net_available,
        'WIP Qty': wip,
        'Total Inventory': total,
        'Stock Status': stock_status,
        'Component Type': f'Unique to {part2}'
    })

# Combine all results
all_results = common_results + unique_results_1 + unique_results_2

# Sort by Component Type then Part Number
all_results.sort(key=lambda x: (x['Component Type'], x['Part Number']))

# Write to CSV
filename = f'common_subassemblies_{part1}_vs_{part2}.csv'
print(f'Writing to {filename}...')

with open(filename, 'w', newline='', encoding='utf-8') as f:
    fieldnames = [
        'Part Number', 'Description', 
        f'BOM Level (in {part1})', f'BOM Level (in {part2})',
        f'Qty per {part1}', f'Qty per {part2}',
        'UOM', 'Has Sub-BOM',
        'Available Qty', 'Committed Qty', 'Net Available', 'WIP Qty', 'Total Inventory',
        'Stock Status', 'Component Type'
    ]
    
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(all_results)

print(f'\nExport complete!')
print(f'File: {filename}')
print(f'Total rows: {len(all_results)}')
print(f'  - Common components: {len(common_results)}')
print(f'  - Unique to {part1}: {len(unique_results_1)}')
print(f'  - Unique to {part2}: {len(unique_results_2)}')

# Also create a summary file
summary_filename = f'common_subassemblies_{part1}_vs_{part2}_summary.txt'
with open(summary_filename, 'w') as f:
    f.write(f'BOM COMPARISON SUMMARY\n')
    f.write(f'=' * 60 + '\n')
    f.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n\n')
    f.write(f'Part 1: {part1} - i-Raman NxG 532\n')
    f.write(f'Part 2: {part2} - i-Raman NxG 785H\n\n')
    
    f.write(f'COMPONENT COUNTS\n')
    f.write(f'-' * 40 + '\n')
    f.write(f'Total in {part1}: {len(part1_all_components)}\n')
    f.write(f'Total in {part2}: {len(part2_all_components)}\n')
    f.write(f'Common components: {len(common_nums)}\n')
    f.write(f'Unique to {part1}: {len(unique_to_1)}\n')
    f.write(f'Unique to {part2}: {len(unique_to_2)}\n\n')
    
    # Stock status counts for common
    in_stock = sum(1 for r in common_results if r['Stock Status'] == 'In Stock')
    wip_only = sum(1 for r in common_results if r['Stock Status'] == 'WIP Only')
    shortage = sum(1 for r in common_results if r['Stock Status'] == 'Shortage')
    
    f.write(f'STOCK STATUS (Common Components Only)\n')
    f.write(f'-' * 40 + '\n')
    f.write(f'In Stock (Net > 0): {in_stock}\n')
    f.write(f'WIP Only (Net <= 0 but WIP > 0): {wip_only}\n')
    f.write(f'Shortage (Net <= 0 and WIP = 0): {shortage}\n\n')
    
    # List common components with stock
    f.write(f'COMMON COMPONENTS WITH AVAILABLE STOCK\n')
    f.write(f'-' * 40 + '\n')
    in_stock_items = [r for r in common_results if r['Stock Status'] == 'In Stock']
    in_stock_items.sort(key=lambda x: -x['Net Available'])
    for r in in_stock_items:
        f.write(f"{r['Part Number']:<18} Net: {r['Net Available']:>6.0f}  {r['Description'][:40]}\n")
    
    f.write(f'\nCOMMON COMPONENTS WITH WIP ONLY\n')
    f.write(f'-' * 40 + '\n')
    wip_items = [r for r in common_results if r['Stock Status'] == 'WIP Only']
    wip_items.sort(key=lambda x: -x['WIP Qty'])
    for r in wip_items:
        f.write(f"{r['Part Number']:<18} WIP: {r['WIP Qty']:>6.0f}  {r['Description'][:40]}\n")

print(f'Summary file: {summary_filename}')

conn.close()
