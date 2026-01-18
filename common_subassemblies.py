import pymysql

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

print(f'=== COMMON SUB-ASSEMBLIES ANALYSIS ===')
print(f'Part 1: {part1}')
print(f'Part 2: {part2}')
print('=' * 60)

# First, verify both parts exist and get their BOM IDs
print('\n--- Part Information ---')
for part_num in [part1, part2]:
    cursor.execute('''
        SELECT p.id, p.num, p.description, p.defaultBomId, b.num as bom_num
        FROM part p
        LEFT JOIN bom b ON p.defaultBomId = b.id
        WHERE p.num = %s
    ''', (part_num,))
    result = cursor.fetchone()
    if result:
        desc = result[2][:50] if result[2] else 'N/A'
        print(f'\nPart: {result[1]}')
        print(f'  Description: {desc}')
        print(f'  Part ID: {result[0]}')
        print(f'  Default BOM ID: {result[3]}')
        print(f'  BOM Number: {result[4]}')
    else:
        print(f'\nPart {part_num} NOT FOUND!')

# Get BOM items for each part
print('\n' + '=' * 60)
print('--- BOM Components for Each Part ---')

# Get components for part 1
cursor.execute('''
    SELECT bi.partId, comp.num, comp.description, bi.quantity, u.code as uom, bit.name as item_type
    FROM part p
    JOIN bom b ON p.defaultBomId = b.id
    JOIN bomitem bi ON bi.bomId = b.id
    JOIN part comp ON bi.partId = comp.id
    JOIN uom u ON bi.uomId = u.id
    JOIN bomitemtype bit ON bi.typeId = bit.id
    WHERE p.num = %s
    ORDER BY comp.num
''', (part1,))
part1_components = cursor.fetchall()

print(f'\n{part1} BOM has {len(part1_components)} components')

# Get components for part 2
cursor.execute('''
    SELECT bi.partId, comp.num, comp.description, bi.quantity, u.code as uom, bit.name as item_type
    FROM part p
    JOIN bom b ON p.defaultBomId = b.id
    JOIN bomitem bi ON bi.bomId = b.id
    JOIN part comp ON bi.partId = comp.id
    JOIN uom u ON bi.uomId = u.id
    JOIN bomitemtype bit ON bi.typeId = bit.id
    WHERE p.num = %s
    ORDER BY comp.num
''', (part2,))
part2_components = cursor.fetchall()

print(f'{part2} BOM has {len(part2_components)} components')

# Find common components (by part ID)
part1_component_ids = {c[0] for c in part1_components}
part2_component_ids = {c[0] for c in part2_components}
common_ids = part1_component_ids & part2_component_ids

print(f'\nCommon components: {len(common_ids)}')

# Create lookup dictionaries
part1_lookup = {c[0]: c for c in part1_components}
part2_lookup = {c[0]: c for c in part2_components}

print('\n' + '=' * 60)
print('--- COMMON SUB-ASSEMBLIES WITH AVAILABLE QUANTITIES ---')
print('=' * 60)

if common_ids:
    results = []
    
    for part_id in common_ids:
        comp = part1_lookup[part_id]
        comp2 = part2_lookup[part_id]
        
        comp_num = comp[1]
        comp_desc = comp[2][:40] if comp[2] else ''
        qty_in_part1 = comp[3]
        qty_in_part2 = comp2[3]
        uom = comp[4]
        item_type = comp[5]
        
        # Get available inventory (countable stock locations)
        cursor.execute('''
            SELECT COALESCE(SUM(t.qty), 0) 
            FROM tag t 
            JOIN location l ON t.locationId = l.id 
            WHERE t.partId = %s AND t.qty > 0 
            AND l.countedAsAvailable = 1
        ''', (part_id,))
        available_qty = cursor.fetchone()[0] or 0
        
        # Get committed quantity
        cursor.execute('''
            SELECT COALESCE(SUM(t.qtyCommitted), 0) 
            FROM tag t 
            JOIN location l ON t.locationId = l.id 
            WHERE t.partId = %s
            AND l.countedAsAvailable = 1
        ''', (part_id,))
        committed_qty = cursor.fetchone()[0] or 0
        
        # Get WIP inventory (Manufacturing locations or tied to WO)
        cursor.execute('''
            SELECT COALESCE(SUM(t.qty), 0) 
            FROM tag t 
            JOIN location l ON t.locationId = l.id 
            WHERE t.partId = %s AND t.qty > 0 
            AND (l.typeId = 80 OR t.woItemId IS NOT NULL)
        ''', (part_id,))
        wip_qty = cursor.fetchone()[0] or 0
        
        # Net available (available - committed)
        net_available = float(available_qty) - float(committed_qty)
        
        results.append({
            'part_num': comp_num,
            'description': comp_desc,
            'qty_in_part1': qty_in_part1,
            'qty_in_part2': qty_in_part2,
            'uom': uom,
            'item_type': item_type,
            'available_qty': float(available_qty),
            'committed_qty': float(committed_qty),
            'net_available': net_available,
            'wip_qty': float(wip_qty)
        })
    
    # Sort by part number
    results.sort(key=lambda x: x['part_num'])
    
    # Print header
    print(f'\n{"Part Number":<20} {"Description":<42} {"Qty in ":<8} {"Qty in ":<8} {"Available":<10} {"Committed":<10} {"Net Avail":<10} {"WIP":<10}')
    print(f'{"":20} {"":42} {part1:<8} {part2:<8} {"":10} {"":10} {"":10} {"":10}')
    print('-' * 150)
    
    for r in results:
        print(f'{r["part_num"]:<20} {r["description"]:<42} {r["qty_in_part1"]:<8.2f} {r["qty_in_part2"]:<8.2f} {r["available_qty"]:<10.0f} {r["committed_qty"]:<10.0f} {r["net_available"]:<10.0f} {r["wip_qty"]:<10.0f}')
    
    # Summary statistics
    print('\n' + '=' * 60)
    print('--- SUMMARY ---')
    print('=' * 60)
    print(f'Total common sub-assemblies: {len(results)}')
    
    # Count how many have adequate stock
    with_stock = sum(1 for r in results if r['net_available'] > 0)
    no_stock = sum(1 for r in results if r['net_available'] <= 0)
    with_wip = sum(1 for r in results if r['net_available'] <= 0 and r['wip_qty'] > 0)
    true_shortage = sum(1 for r in results if r['net_available'] <= 0 and r['wip_qty'] <= 0)
    
    print(f'\nStock Status:')
    print(f'  With available stock (net > 0): {with_stock}')
    print(f'  No available stock (net <= 0): {no_stock}')
    print(f'    - With WIP inventory: {with_wip}')
    print(f'    - TRUE shortage (no WIP): {true_shortage}')
    
    # Show parts with stock issues
    shortages = [r for r in results if r['net_available'] <= 0]
    if shortages:
        print('\n--- Parts with Stock Issues ---')
        for r in shortages:
            status = 'WIP available' if r['wip_qty'] > 0 else 'TRUE SHORTAGE'
            print(f'  {r["part_num"]}: Net Available = {r["net_available"]:.0f}, WIP = {r["wip_qty"]:.0f} [{status}]')
else:
    print('\nNo common components found between the two BOMs.')

# Also show unique components for reference
print('\n' + '=' * 60)
print('--- UNIQUE COMPONENTS (for reference) ---')
print('=' * 60)

unique_to_part1 = part1_component_ids - common_ids
unique_to_part2 = part2_component_ids - common_ids

print(f'\nComponents ONLY in {part1}: {len(unique_to_part1)}')
if unique_to_part1:
    for part_id in sorted(unique_to_part1, key=lambda x: part1_lookup[x][1]):
        c = part1_lookup[part_id]
        desc = c[2][:40] if c[2] else ''
        print(f'  {c[1]:<20} {desc:<40} Qty: {c[3]}')

print(f'\nComponents ONLY in {part2}: {len(unique_to_part2)}')
if unique_to_part2:
    for part_id in sorted(unique_to_part2, key=lambda x: part2_lookup[x][1]):
        c = part2_lookup[part_id]
        desc = c[2][:40] if c[2] else ''
        print(f'  {c[1]:<20} {desc:<40} Qty: {c[3]}')

conn.close()
print('\n--- Analysis Complete ---')
