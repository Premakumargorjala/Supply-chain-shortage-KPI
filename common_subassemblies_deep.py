import pymysql
from collections import defaultdict

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
        
        # Skip if this is the finished good (same as parent)
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
        
        # Recursively get sub-components if this part has a BOM
        if has_bom and level < 5:  # Limit depth to prevent infinite loops
            sub_components = get_bom_components(comp_num, level + 1, path)
            components.extend(sub_components)
    
    return components

def get_inventory(part_id):
    """Get inventory quantities for a part"""
    # Available inventory
    cursor.execute('''
        SELECT COALESCE(SUM(t.qty), 0) 
        FROM tag t 
        JOIN location l ON t.locationId = l.id 
        WHERE t.partId = %s AND t.qty > 0 
        AND l.countedAsAvailable = 1
    ''', (part_id,))
    available_qty = cursor.fetchone()[0] or 0
    
    # Committed quantity
    cursor.execute('''
        SELECT COALESCE(SUM(t.qtyCommitted), 0) 
        FROM tag t 
        JOIN location l ON t.locationId = l.id 
        WHERE t.partId = %s
        AND l.countedAsAvailable = 1
    ''', (part_id,))
    committed_qty = cursor.fetchone()[0] or 0
    
    # WIP inventory
    cursor.execute('''
        SELECT COALESCE(SUM(t.qty), 0) 
        FROM tag t 
        JOIN location l ON t.locationId = l.id 
        WHERE t.partId = %s AND t.qty > 0 
        AND (l.typeId = 80 OR t.woItemId IS NOT NULL)
    ''', (part_id,))
    wip_qty = cursor.fetchone()[0] or 0
    
    return float(available_qty), float(committed_qty), float(wip_qty)

print(f'=== DEEP BOM ANALYSIS: COMMON SUB-ASSEMBLIES ===')
print(f'Part 1: {part1}')
print(f'Part 2: {part2}')
print('=' * 80)

# Get all components recursively for both parts
print('\nExploding BOMs (this may take a moment)...')
part1_all_components = get_bom_components(part1)
part2_all_components = get_bom_components(part2)

print(f'\n{part1} total components (all levels): {len(part1_all_components)}')
print(f'{part2} total components (all levels): {len(part2_all_components)}')

# Create lookup by part_num (use part_num as key since same part can appear at different levels)
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
print(f'\nCommon components across all BOM levels: {len(common_nums)}')

# Get inventory for all common parts
print('\n' + '=' * 80)
print('COMMON SUB-ASSEMBLIES WITH AVAILABLE QUANTITIES')
print('=' * 80)

results = []
for part_num in common_nums:
    c1 = part1_by_num[part_num]
    c2 = part2_by_num[part_num]
    
    available, committed, wip = get_inventory(c1['part_id'])
    net_available = available - committed
    
    results.append({
        'part_num': part_num,
        'description': c1['description'][:45] if c1['description'] else '',
        'level_in_part1': c1['level'],
        'level_in_part2': c2['level'],
        'qty_in_part1': c1['quantity'],
        'qty_in_part2': c2['quantity'],
        'has_bom': c1['has_bom'],
        'available': available,
        'committed': committed,
        'net_available': net_available,
        'wip': wip
    })

# Sort by part number
results.sort(key=lambda x: x['part_num'])

# Print results
print(f'\n{"Part Number":<18} {"Description":<47} {"Lvl":<4} {"Avail":<8} {"Commit":<8} {"Net":<8} {"WIP":<8} {"Has BOM":<8}')
print('-' * 125)

for r in results:
    has_bom_str = 'Yes' if r['has_bom'] else 'No'
    print(f'{r["part_num"]:<18} {r["description"]:<47} {r["level_in_part1"]:<4} {r["available"]:<8.0f} {r["committed"]:<8.0f} {r["net_available"]:<8.0f} {r["wip"]:<8.0f} {has_bom_str:<8}')

# Summary
print('\n' + '=' * 80)
print('SUMMARY')
print('=' * 80)

# Count by level
by_level = defaultdict(int)
for r in results:
    by_level[r['level_in_part1']] += 1

print(f'\nTotal common components: {len(results)}')
print(f'\nBy BOM Level:')
for level in sorted(by_level.keys()):
    print(f'  Level {level}: {by_level[level]} components')

# Stock status
with_stock = [r for r in results if r['net_available'] > 0]
no_stock = [r for r in results if r['net_available'] <= 0]
with_wip = [r for r in results if r['net_available'] <= 0 and r['wip'] > 0]
true_shortage = [r for r in results if r['net_available'] <= 0 and r['wip'] <= 0]

print(f'\nStock Status:')
print(f'  With available stock (net > 0): {len(with_stock)}')
print(f'  No available stock (net <= 0): {len(no_stock)}')
if no_stock:
    print(f'    - With WIP inventory: {len(with_wip)}')
    print(f'    - TRUE shortage (no WIP): {len(true_shortage)}')

# Show parts that are sub-assemblies (have their own BOM)
sub_assemblies = [r for r in results if r['has_bom']]
raw_materials = [r for r in results if not r['has_bom']]

print(f'\nComponent Types:')
print(f'  Sub-assemblies (have own BOM): {len(sub_assemblies)}')
print(f'  Raw materials/parts (no BOM): {len(raw_materials)}')

# Show shortages if any
if true_shortage:
    print('\n' + '=' * 80)
    print('PARTS WITH TRUE SHORTAGES (no available stock and no WIP)')
    print('=' * 80)
    for r in true_shortage:
        print(f'  {r["part_num"]:<18} {r["description"]:<45} Net: {r["net_available"]:.0f}')

# Show parts with WIP only
if with_wip:
    print('\n' + '=' * 80)
    print('PARTS WITH WIP ONLY (waiting on manufacturing)')
    print('=' * 80)
    for r in with_wip:
        print(f'  {r["part_num"]:<18} {r["description"]:<45} WIP: {r["wip"]:.0f}')

# Show unique parts at each level for reference
print('\n' + '=' * 80)
print('UNIQUE COMPONENTS (NOT SHARED)')
print('=' * 80)

unique_to_1 = set(part1_by_num.keys()) - common_nums
unique_to_2 = set(part2_by_num.keys()) - common_nums

print(f'\nUnique to {part1}: {len(unique_to_1)} components')
for pn in sorted(unique_to_1):
    c = part1_by_num[pn]
    desc = c['description'][:40] if c['description'] else ''
    print(f'  L{c["level"]}: {pn:<18} {desc}')

print(f'\nUnique to {part2}: {len(unique_to_2)} components')
for pn in sorted(unique_to_2):
    c = part2_by_num[pn]
    desc = c['description'][:40] if c['description'] else ''
    print(f'  L{c["level"]}: {pn:<18} {desc}')

conn.close()
print('\n--- Deep Analysis Complete ---')
