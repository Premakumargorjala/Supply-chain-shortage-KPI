import pymysql

conn = pymysql.connect(
    host='451-srv-fbwl01',
    port=3306,
    user='ReadUser',
    password='Metrohm2026!',
    database='MetrohmSpectro'
)

cursor = conn.cursor()

print('=== CHECKING MO 183 FOR PART 200022152 ===\n')

# Find MO 183
cursor.execute('''
    SELECT mo.id, mo.num, mo.statusId, ms.name as mo_status
    FROM mo
    JOIN mostatus ms ON mo.statusId = ms.id
    WHERE mo.num = '183'
''')
mo_result = cursor.fetchone()
if mo_result:
    print(f'MO Number: {mo_result[1]}')
    print(f'MO Status: {mo_result[3]}')
    print(f'MO ID: {mo_result[0]}')
    mo_id = mo_result[0]
else:
    print('MO 183 not found')
    mo_id = None

# Get all MOitems for MO 183
print('\n=== MO ITEMS IN MO 183 ===')
cursor.execute('''
    SELECT 
        moitem.id,
        p.num as part_num,
        p.description,
        bit.name as item_type,
        moitem.qtyToFulfill,
        moitem.qtyFulfilled,
        mis.name as status
    FROM moitem
    JOIN mo ON moitem.moId = mo.id
    JOIN part p ON moitem.partId = p.id
    JOIN bomitemtype bit ON moitem.typeId = bit.id
    JOIN moitemstatus mis ON moitem.statusId = mis.id
    WHERE mo.num = '183'
    ORDER BY bit.id, p.num
''')
moitems = cursor.fetchall()

header = f"{'Part':<25} {'Type':<18} {'Status':<12} {'ToFulfill':<10} {'Fulfilled':<10}"
print(f'\n{header}')
print('-' * 85)
for item in moitems:
    part_num = str(item[1])[:25]
    item_type = str(item[3])[:18]
    status = str(item[6])[:12]
    highlight = ' <-- THIS PART' if '200022152' in str(item[1]) else ''
    print(f'{part_num:<25} {item_type:<18} {status:<12} {item[4]:<10} {item[5]:<10}{highlight}')

# Specifically check if 200022152 is being manufactured (Finished Good type)
print('\n=== CHECKING IF 200022152 IS BEING MANUFACTURED ===')
cursor.execute('''
    SELECT 
        mo.num as mo_num,
        moitem.id as moitem_id,
        p.num as part_num,
        p.description,
        bit.name as item_type,
        moitem.qtyToFulfill,
        moitem.qtyFulfilled,
        mis.name as moitem_status,
        ms.name as mo_status
    FROM moitem
    JOIN mo ON moitem.moId = mo.id
    JOIN mostatus ms ON mo.statusId = ms.id
    JOIN part p ON moitem.partId = p.id
    JOIN bomitemtype bit ON moitem.typeId = bit.id
    JOIN moitemstatus mis ON moitem.statusId = mis.id
    WHERE p.num = '200022152'
    AND bit.id = 10  -- Finished Good type
''')
fg_items = cursor.fetchall()

if fg_items:
    print('\nPart 200022152 IS being manufactured as a Finished Good:')
    for fg in fg_items:
        print(f'  MO: {fg[0]}, MOItem ID: {fg[1]}')
        print(f'  Part: {fg[2]} - {fg[3]}')
        print(f'  Type: {fg[4]}')
        print(f'  Qty To Fulfill: {fg[5]}, Qty Fulfilled: {fg[6]}')
        print(f'  MOItem Status: {fg[7]}, MO Status: {fg[8]}')
        
    # THIS IS THE KEY - if a part is being manufactured in an open MO, it's WIP!
    print('\n*** THIS MEANS THE PART SHOULD BE WIP_SHORTAGE, NOT TRUE_SHORTAGE! ***')
else:
    print('Part 200022152 is NOT being manufactured as a Finished Good in any MO')

# Also check all open MOs where this part appears as ANY type
print('\n=== ALL MO ITEMS FOR PART 200022152 ===')
cursor.execute('''
    SELECT 
        mo.num as mo_num,
        moitem.id as moitem_id,
        bit.name as item_type,
        moitem.qtyToFulfill,
        moitem.qtyFulfilled,
        mis.name as moitem_status,
        ms.name as mo_status
    FROM moitem
    JOIN mo ON moitem.moId = mo.id
    JOIN mostatus ms ON mo.statusId = ms.id
    JOIN part p ON moitem.partId = p.id
    JOIN bomitemtype bit ON moitem.typeId = bit.id
    JOIN moitemstatus mis ON moitem.statusId = mis.id
    WHERE p.num = '200022152'
''')
all_items = cursor.fetchall()

if all_items:
    print(f"{'MO':<10} {'Type':<18} {'MO Status':<12} {'Item Status':<12} {'ToFulfill':<10} {'Fulfilled':<10}")
    print('-' * 80)
    for item in all_items:
        print(f'{item[0]:<10} {item[2]:<18} {item[6]:<12} {item[5]:<12} {item[3]:<10} {item[4]:<10}')

conn.close()
