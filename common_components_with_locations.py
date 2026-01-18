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

part1 = '200022240-H-HT'
part2 = '200022239-HT'

def get_part_info(part_num):
    """Get part details"""
    cursor.execute('''
        SELECT p.id, p.num, p.description, p.defaultBomId, b.num as bom_num
        FROM part p
        LEFT JOIN bom b ON p.defaultBomId = b.id
        WHERE p.num = %s
    ''', (part_num,))
    return cursor.fetchone()

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

def get_inventory_with_locations(part_id):
    """Get inventory quantities with location breakdown"""
    # Get all inventory by location
    cursor.execute('''
        SELECT l.name as location, lt.name as loc_type, lg.name as loc_group,
               t.qty, t.qtyCommitted, l.countedAsAvailable,
               CASE WHEN t.woItemId IS NOT NULL THEN 'WIP' ELSE 'Stock' END as inv_type
        FROM tag t
        JOIN location l ON t.locationId = l.id
        JOIN locationtype lt ON l.typeId = lt.id
        JOIN locationgroup lg ON l.locationGroupId = lg.id
        WHERE t.partId = %s AND t.qty > 0
        ORDER BY l.countedAsAvailable DESC, t.qty DESC
    ''', (part_id,))
    locations = cursor.fetchall()
    
    # Calculate totals
    available_qty = sum(row[3] for row in locations if row[5])  # countedAsAvailable = 1
    committed_qty = sum(row[4] for row in locations if row[5])
    wip_qty = sum(row[3] for row in locations if row[6] == 'WIP' or row[1] == 'Manufacturing')
    total_qty = sum(row[3] for row in locations)
    
    return {
        'available': float(available_qty),
        'committed': float(committed_qty),
        'net_available': float(available_qty - committed_qty),
        'wip': float(wip_qty),
        'total': float(total_qty),
        'locations': locations
    }

print(f'=== COMMON COMPONENTS ANALYSIS WITH LOCATIONS ===')
print(f'Part 1: {part1}')
print(f'Part 2: {part2}')
print('=' * 80)

# Verify parts exist
print('\n--- Part Information ---')
for pn in [part1, part2]:
    info = get_part_info(pn)
    if info:
        desc = info[2][:60] if info[2] else 'N/A'
        print(f'\nPart: {info[1]}')
        print(f'  Description: {desc}')
        print(f'  Part ID: {info[0]}')
        print(f'  Default BOM: {info[4]}')
    else:
        print(f'\nPart {pn} NOT FOUND!')

# Get all components
print('\nExploding BOMs...')
part1_components = get_bom_components(part1)
part2_components = get_bom_components(part2)

print(f'{part1}: {len(part1_components)} components')
print(f'{part2}: {len(part2_components)} components')

# Create lookups
part1_by_num = {c['part_num']: c for c in part1_components if c['part_num'] not in [p['part_num'] for p in part1_components[:part1_components.index(c)]]}
part2_by_num = {c['part_num']: c for c in part2_components if c['part_num'] not in [p['part_num'] for p in part2_components[:part2_components.index(c)]]}

# Simpler approach - just take first occurrence
part1_by_num = {}
for c in part1_components:
    if c['part_num'] not in part1_by_num:
        part1_by_num[c['part_num']] = c

part2_by_num = {}
for c in part2_components:
    if c['part_num'] not in part2_by_num:
        part2_by_num[c['part_num']] = c

# Find common
common_nums = set(part1_by_num.keys()) & set(part2_by_num.keys())
unique_to_1 = set(part1_by_num.keys()) - common_nums
unique_to_2 = set(part2_by_num.keys()) - common_nums

print(f'\nCommon components: {len(common_nums)}')
print(f'Unique to {part1}: {len(unique_to_1)}')
print(f'Unique to {part2}: {len(unique_to_2)}')

# Gather data for common components
print('\nFetching inventory with locations...')

common_results = []
location_details = []

for part_num in sorted(common_nums):
    c1 = part1_by_num[part_num]
    c2 = part2_by_num[part_num]
    
    inv = get_inventory_with_locations(c1['part_id'])
    
    # Determine stock status
    if inv['net_available'] > 0:
        stock_status = 'In Stock'
    elif inv['wip'] > 0:
        stock_status = 'WIP Only'
    else:
        stock_status = 'Shortage'
    
    common_results.append({
        'part_num': part_num,
        'description': c1['description'] or '',
        'level_1': c1['level'],
        'level_2': c2['level'],
        'qty_1': float(c1['quantity']),
        'qty_2': float(c2['quantity']),
        'has_bom': c1['has_bom'],
        'available': inv['available'],
        'committed': inv['committed'],
        'net_available': inv['net_available'],
        'wip': inv['wip'],
        'total': inv['total'],
        'stock_status': stock_status,
        'locations': inv['locations']
    })
    
    # Store location details for separate export
    for loc in inv['locations']:
        location_details.append({
            'Part Number': part_num,
            'Description': c1['description'][:50] if c1['description'] else '',
            'Location': loc[0],
            'Location Type': loc[1],
            'Location Group': loc[2],
            'Qty On Hand': float(loc[3]),
            'Qty Committed': float(loc[4]),
            'Counted As Available': 'Yes' if loc[5] else 'No',
            'Inventory Type': loc[6]
        })

# Print summary
print('\n' + '=' * 100)
print('COMMON COMPONENTS WITH AVAILABLE QUANTITIES')
print('=' * 100)

# Print header
print(f'\n{"Part Number":<22} {"Description":<40} {"Lvl":<4} {"Avail":<8} {"Commit":<8} {"Net":<8} {"WIP":<8} {"Status":<12} {"Has BOM":<8}')
print('-' * 130)

for r in common_results:
    desc = r['description'][:38] if r['description'] else ''
    has_bom = 'Yes' if r['has_bom'] else 'No'
    print(f'{r["part_num"]:<22} {desc:<40} {r["level_1"]:<4} {r["available"]:<8.0f} {r["committed"]:<8.0f} {r["net_available"]:<8.0f} {r["wip"]:<8.0f} {r["stock_status"]:<12} {has_bom:<8}')

# Show sub-assemblies (components with their own BOM)
print('\n' + '=' * 100)
print('COMMON SUB-ASSEMBLIES (components that have their own BOM)')
print('=' * 100)

sub_assemblies = [r for r in common_results if r['has_bom']]
print(f'\nFound {len(sub_assemblies)} common sub-assemblies:\n')

for r in sub_assemblies:
    desc = r['description'][:50] if r['description'] else ''
    print(f'{r["part_num"]:<22} L{r["level_1"]} Net: {r["net_available"]:>6.0f}  {desc}')

# Show location details for components with stock
print('\n' + '=' * 100)
print('INVENTORY LOCATION DETAILS (for components with stock)')
print('=' * 100)

for r in common_results:
    if r['locations']:
        print(f'\n{r["part_num"]} - {r["description"][:45]}')
        print(f'  {"Location":<25} {"Type":<15} {"Qty":<10} {"Committed":<10} {"Available?":<10}')
        print('  ' + '-' * 75)
        for loc in r['locations']:
            avail = 'Yes' if loc[5] else 'No'
            print(f'  {loc[0]:<25} {loc[1]:<15} {loc[3]:<10.0f} {loc[4]:<10.0f} {avail:<10}')

# Summary stats
print('\n' + '=' * 100)
print('SUMMARY')
print('=' * 100)

in_stock = sum(1 for r in common_results if r['stock_status'] == 'In Stock')
wip_only = sum(1 for r in common_results if r['stock_status'] == 'WIP Only')
shortage = sum(1 for r in common_results if r['stock_status'] == 'Shortage')

print(f'\nTotal common components: {len(common_results)}')
print(f'  Sub-assemblies (have own BOM): {len(sub_assemblies)}')
print(f'  Raw materials/parts: {len(common_results) - len(sub_assemblies)}')
print(f'\nStock Status:')
print(f'  In Stock (Net > 0): {in_stock}')
print(f'  WIP Only: {wip_only}')
print(f'  Shortage: {shortage}')

# Export to CSV
filename = f'common_components_{part1.replace("-", "_")}_vs_{part2.replace("-", "_")}.csv'
print(f'\nExporting to {filename}...')

with open(filename, 'w', newline='', encoding='utf-8') as f:
    fieldnames = [
        'Part Number', 'Description', 
        f'BOM Level ({part1})', f'BOM Level ({part2})',
        f'Qty per {part1}', f'Qty per {part2}',
        'Has Sub-BOM', 'Available Qty', 'Committed Qty', 'Net Available', 
        'WIP Qty', 'Total Inventory', 'Stock Status'
    ]
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    
    for r in common_results:
        writer.writerow({
            'Part Number': r['part_num'],
            'Description': r['description'],
            f'BOM Level ({part1})': r['level_1'],
            f'BOM Level ({part2})': r['level_2'],
            f'Qty per {part1}': r['qty_1'],
            f'Qty per {part2}': r['qty_2'],
            'Has Sub-BOM': 'Yes' if r['has_bom'] else 'No',
            'Available Qty': r['available'],
            'Committed Qty': r['committed'],
            'Net Available': r['net_available'],
            'WIP Qty': r['wip'],
            'Total Inventory': r['total'],
            'Stock Status': r['stock_status']
        })

# Export location details
loc_filename = f'common_components_{part1.replace("-", "_")}_vs_{part2.replace("-", "_")}_locations.csv'
print(f'Exporting location details to {loc_filename}...')

with open(loc_filename, 'w', newline='', encoding='utf-8') as f:
    if location_details:
        writer = csv.DictWriter(f, fieldnames=location_details[0].keys())
        writer.writeheader()
        writer.writerows(location_details)

print(f'\nExport complete!')
print(f'  Components: {filename}')
print(f'  Location details: {loc_filename}')

conn.close()
