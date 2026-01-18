import pymysql

conn = pymysql.connect(
    host='451-srv-fbwl01',
    port=3306,
    user='ReadUser',
    password='Metrohm2026!',
    database='MetrohmSpectro'
)

cursor = conn.cursor()

# Find WO 183:003 and check part 20022152
print('=== CHECKING WO 183:003 FOR PART 20022152 ===\n')

# First, find the WO
cursor.execute('''
    SELECT wo.id, wo.num, wo.statusId, ws.name as wo_status
    FROM wo
    JOIN wostatus ws ON wo.statusId = ws.id
    WHERE wo.num = '183:003'
''')
wo_result = cursor.fetchone()

if wo_result:
    print(f'Work Order: {wo_result[1]}')
    print(f'WO Status: {wo_result[3]}')
    print(f'WO ID: {wo_result[0]}')
    wo_id = wo_result[0]
else:
    print('WO 183:003 not found!')
    wo_id = None

# First show all items in this WO
print('\n=== ALL ITEMS IN WO 183:003 ===')
cursor.execute('''
    SELECT wi.id, p.num, p.description, wi.qtyTarget, wi.qtyUsed
    FROM woitem wi
    JOIN wo ON wi.woId = wo.id
    JOIN part p ON wi.partId = p.id
    WHERE wo.num = '183:003'
    ORDER BY p.num
''')
wo_items = cursor.fetchall()
for r in wo_items:
    desc = r[2][:40] if r[2] else ''
    print(f'  {r[1]:<25} Target: {r[3]:<5} Used: {r[4]}')

# Find the part - try multiple patterns
print('\n=== SEARCHING FOR PART 20022152 ===')
patterns = ['%20022152%', '200022152%', '%00022152%', '20022152', '200022152']
part_results = []
for pattern in patterns:
    cursor.execute('SELECT p.id, p.num, p.description FROM part p WHERE p.num LIKE %s', (pattern,))
    results = cursor.fetchall()
    if results:
        print(f'Found with pattern {pattern}:')
        for r in results:
            desc = r[2][:50] if r[2] else ''
            print(f'  Part ID: {r[0]}, Num: {r[1]}, Desc: {desc}')
            part_results.append(r)
        break

if not part_results:
    # Check if it's in the WO items list
    print('Part not found by number search. Checking WO items...')
    for wo_item in wo_items:
        if '22152' in wo_item[1]:
            print(f'  Possible match in WO: {wo_item[1]}')

if part_results:
    part_id = part_results[0][0]
    part_num = part_results[0][1]
    
    # Check if this part is in the WO items
    if wo_id:
        cursor.execute('''
            SELECT wi.id, wi.qtyTarget, wi.qtyUsed, p.num
            FROM woitem wi
            JOIN part p ON wi.partId = p.id
            WHERE wi.woId = %s AND p.num LIKE %s
        ''', (wo_id, '%20022152%'))
        woitem = cursor.fetchall()
        print(f'\nWO Items matching this part in WO 183:003:')
        for w in woitem:
            print(f'  WOItem ID: {w[0]}, Qty Target: {w[1]}, Qty Used: {w[2]}, Part: {w[3]}')
    
    # Check inventory status for this part
    print(f'\n=== INVENTORY ANALYSIS FOR PART {part_num} ===\n')
    
    # Available inventory
    cursor.execute('''
        SELECT COALESCE(SUM(t.qty), 0) 
        FROM tag t 
        JOIN location l ON t.locationId = l.id 
        WHERE t.partId = %s AND t.qty > 0 
        AND l.countedAsAvailable = 1
    ''', (part_id,))
    available_qty = cursor.fetchone()[0]
    
    # WIP inventory
    cursor.execute('''
        SELECT COALESCE(SUM(t.qty), 0) 
        FROM tag t 
        JOIN location l ON t.locationId = l.id 
        WHERE t.partId = %s AND t.qty > 0 
        AND (l.typeId = 80 OR t.woItemId IS NOT NULL)
    ''', (part_id,))
    wip_qty = cursor.fetchone()[0]
    
    # Total inventory
    cursor.execute('''
        SELECT COALESCE(SUM(t.qty), 0) 
        FROM tag t 
        WHERE t.partId = %s AND t.qty > 0
    ''', (part_id,))
    total_qty = cursor.fetchone()[0]
    
    # Show all tag locations for this part
    cursor.execute('''
        SELECT l.name, lt.name as loc_type, l.countedAsAvailable, t.qty, t.woItemId,
               CASE WHEN t.woItemId IS NOT NULL THEN 
                   (SELECT wo.num FROM woitem wi JOIN wo ON wi.woId = wo.id WHERE wi.id = t.woItemId)
               ELSE NULL END as related_wo
        FROM tag t
        JOIN location l ON t.locationId = l.id
        JOIN locationtype lt ON l.typeId = lt.id
        WHERE t.partId = %s AND t.qty > 0
    ''', (part_id,))
    tags = cursor.fetchall()
    
    print(f'Available Qty (in countable stock): {available_qty}')
    print(f'WIP Qty (Mfg locations or tied to WO): {wip_qty}')
    print(f'Total Qty (all locations): {total_qty}')
    
    if tags:
        print(f'\nInventory by Location:')
        print(f'  {"Location":<25} {"Type":<15} {"Countable":<10} {"Qty":<10} {"Related WO":<15}')
        print('  ' + '-' * 80)
        for tag in tags:
            countable = 'Yes' if tag[2] else 'No'
            related_wo = tag[5] if tag[5] else '-'
            print(f'  {tag[0]:<25} {tag[1]:<15} {countable:<10} {tag[3]:<10.0f} {related_wo:<15}')
    else:
        print('\nNo inventory found for this part!')
    
    # Determine shortage category
    print(f'\n=== SHORTAGE CATEGORIZATION ===')
    if available_qty <= 0 and wip_qty <= 0:
        category = 'TRUE_SHORTAGE'
    elif available_qty <= 0 and wip_qty > 0:
        category = 'WIP_SHORTAGE'
    else:
        category = 'COMMITTED_ELSEWHERE (or not short)'
    
    print(f'\nCategory: {category}')
    print(f'\nReasoning:')
    print(f'  - Available Qty = {available_qty} (countable stock locations)')
    print(f'  - WIP Qty = {wip_qty} (Mfg locations or tied to WO)')
    if category == 'TRUE_SHORTAGE':
        print(f'  - Both are zero -> TRUE_SHORTAGE (need to purchase)')
    elif category == 'WIP_SHORTAGE':
        print(f'  - Available is zero BUT WIP has qty -> WIP_SHORTAGE (wait for WO)')
    else:
        print(f'  - Available qty exists -> Not a true shortage')

    # Check if this part is in any short pick items
    cursor.execute('''
        SELECT pi.id, pis.name as status, pk.id as pick_id
        FROM pickitem pi
        JOIN pickitemstatus pis ON pi.statusId = pis.id
        JOIN pick pk ON pi.pickId = pk.id
        WHERE pi.partId = %s AND pi.statusId = 5
    ''', (part_id,))
    picks = cursor.fetchall()
    if picks:
        print(f'\nShort Pick Items for this part:')
        for pk in picks:
            print(f'  PickItem ID: {pk[0]}, Status: {pk[1]}, Pick ID: {pk[2]}')
    else:
        print(f'\nNo short pick items found for this part.')

conn.close()
