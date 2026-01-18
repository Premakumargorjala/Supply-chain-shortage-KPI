# MetrohmSpectro Database Reference Guide

> **Last Updated:** January 17, 2026  
> **Database Type:** Fishbowl Inventory (MySQL)  
> **Reference:** [Fishbowl Database Tables](https://fishbowlhelp.com/files/database/tables)

---

## 📌 Connection Details

| Property | Value |
|----------|-------|
| **Server** | `451-srv-fbwl01` |
| **Port** | `3306` |
| **Database** | `MetrohmSpectro` |
| **Read User** | `ReadUser` |
| **Password** | `Metrohm2026!` |

### Python Connection Example

```python
import pymysql

conn = pymysql.connect(
    host='451-srv-fbwl01',
    port=3306,
    user='ReadUser',
    password='Metrohm2026!',
    database='MetrohmSpectro'
)
cursor = conn.cursor()
```

---

## 📊 Database Overview

This is a **Fishbowl Inventory** ERP database used for:
- Inventory Management
- Sales Orders (SO)
- Purchase Orders (PO)
- Manufacturing Orders (MO)
- Work Orders (WO)
- Bill of Materials (BOM)
- Warehouse/Location Management

### Location Groups
| ID | Name | Active |
|----|------|--------|
| 1 | Main | Yes |
| 2 | B&WTek Branding | Yes |

---

## 🔗 Entity Relationship Diagram

```
                              ┌──────────────┐
                              │   account    │
                              │   (768)      │
                              └──────┬───────┘
                         ┌──────────┴───────────┐
                         ▼                       ▼
                  ┌───────────┐           ┌───────────┐
                  │ customer  │           │  vendor   │
                  │   (248)   │           │   (519)   │
                  └─────┬─────┘           └─────┬─────┘
                        │                       │
                        ▼                       ▼
                  ┌───────────┐           ┌───────────┐
                  │    so     │           │    po     │
                  │   (286)   │           │   (420)   │
                  └─────┬─────┘           └─────┬─────┘
                        │                       │
                        ▼                       ▼
                  ┌───────────┐           ┌───────────┐
                  │  soitem   │◄─product  │  poitem   │◄─part
                  │  (1,313)  │           │   (977)   │
                  └─────┬─────┘           └─────┬─────┘
                        │                       │
          ┌─────────────┼─────────────┐         │
          ▼             ▼             ▼         ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐ ┌─────────┐
    │  pick   │   │   mo    │   │  ship   │ │ receipt │
    │ (2,373) │   │  (528)  │   │  (186)  │ │  (417)  │
    └────┬────┘   └────┬────┘   └────┬────┘ └────┬────┘
         │             │             │           │
         ▼             ▼             ▼           ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐ ┌─────────┐
    │pickitem │   │ moitem  │   │shipitem │ │receiptitem│
    │(20,281) │   │(25,570) │   │  (517)  │ │ (1,081) │
    └─────────┘   └────┬────┘   └─────────┘ └─────────┘
                       │
                       ▼
                  ┌─────────┐
                  │   wo    │
                  │ (2,132) │
                  └────┬────┘
                       │
                       ▼
                  ┌─────────┐       ┌─────────┐
                  │ woitem  │◄──────│   bom   │
                  │(21,874) │       │ (1,133) │
                  └────┬────┘       └────┬────┘
                       │                 │
                       ▼                 ▼
                  ┌─────────┐       ┌─────────┐
                  │   tag   │       │ bomitem │
                  │ (9,290) │       │ (8,673) │
                  └────┬────┘       └─────────┘
                       │
                       ▼
            ┌──────────────────┐
            │  inventorylog    │
            │    (34,563)      │
            └──────────────────┘
```

---

## 📋 Core Tables Reference

### Master Data Tables

#### `part` - Inventory Parts (6,278 rows)
Raw materials, components, assemblies - the core inventory items.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| num | varchar(70) | UNI | Part number |
| description | varchar(252) | | Part description |
| typeId | int | FK→parttype | Part type |
| uomId | int | FK→uom | Unit of measure |
| activeFlag | bit(1) | | Is active |
| stdCost | decimal(28,9) | | Standard cost |
| defaultBomId | int | FK→bom | Default BOM |
| defaultProductId | int | FK→product | Default sellable product |
| trackingFlag | bit(1) | | Has tracking enabled |
| serializedFlag | bit(1) | | Is serialized |
| weight | decimal(28,9) | | Weight |
| dateCreated | datetime | | Created date |
| dateLastModified | datetime | | Last modified date |
| customFields | json | | Custom field values |

#### `product` - Sellable Products (1,332 rows)
Products that can be sold (linked to parts).

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| num | varchar(70) | UNI | Product number |
| description | varchar(252) | | Product description |
| partId | int | FK→part | Linked inventory part |
| price | decimal(28,9) | | Default price |
| uomId | int | FK→uom | Selling UOM |
| activeFlag | bit(1) | | Is active |
| kitFlag | bit(1) | | Is a kit |
| taxableFlag | bit(1) | | Is taxable |
| incomeAccountId | int | FK→asaccount | Income account |
| customFields | json | | Custom field values |

#### `customer` - Customers (248 rows)
Customer accounts.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| accountId | int | FK→account | Base account |
| name | varchar(41) | | Customer name |
| number | varchar(30) | UNI | Customer number |
| statusId | int | FK→customerstatus | Status |
| activeFlag | bit(1) | | Is active |
| creditLimit | decimal(28,9) | | Credit limit |
| defaultPaymentTermsId | int | FK→paymentterms | Default payment terms |
| taxExempt | bit(1) | | Tax exempt flag |
| parentId | int | FK→customer | Parent customer (for hierarchy) |
| customFields | json | | Custom field values |

#### `vendor` - Vendors/Suppliers (519 rows)
Vendor/supplier accounts.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| accountId | int | FK→account | Base account |
| name | varchar(41) | UNI | Vendor name |
| accountNum | varchar(30) | | Vendor's account number for us |
| statusId | int | FK→vendorstatus | Status |
| activeFlag | bit(1) | | Is active |
| leadTime | int | | Default lead time (days) |
| defaultPaymentTermsId | int | FK→paymentterms | Default payment terms |
| customFields | json | | Custom field values |

---

### Sales Order Tables

#### `so` - Sales Orders (286 rows)
Sales order headers.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| num | varchar(25) | UNI | SO number |
| customerId | int | FK→customer | Customer |
| statusId | int | FK→sostatus | Status |
| dateCreated | datetime | | Created date |
| dateIssued | datetime | | Issued date |
| dateCompleted | datetime | | Completed date |
| totalPrice | decimal(28,9) | | Total price |
| subTotal | decimal(28,9) | | Subtotal |
| totalTax | decimal(28,9) | | Total tax |
| salesmanId | int | FK→sysuser | Salesman |
| customerPO | varchar(25) | | Customer PO number |
| locationGroupId | int | FK→locationgroup | Location group |
| priorityId | int | FK→priority | Priority |
| carrierId | int | FK→carrier | Carrier |
| paymentTermsId | int | FK→paymentterms | Payment terms |
| customFields | json | | Custom field values |

#### `soitem` - Sales Order Items (1,313 rows)
Sales order line items.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| soId | int | FK→so | Parent SO |
| soLineItem | int | | Line number |
| productId | int | FK→product | Product |
| productNum | varchar(70) | | Product number |
| description | varchar(256) | | Description |
| qtyOrdered | decimal(28,9) | | Quantity ordered |
| qtyFulfilled | decimal(28,9) | | Quantity fulfilled |
| qtyPicked | decimal(28,9) | | Quantity picked |
| unitPrice | decimal(28,9) | | Unit price |
| totalPrice | decimal(28,9) | | Total price |
| statusId | int | FK→soitemstatus | Status |
| typeId | int | FK→soitemtype | Item type |
| dateScheduledFulfillment | datetime | | Scheduled date |
| uomId | int | FK→uom | UOM |
| customFields | json | | Custom field values |

---

### Purchase Order Tables

#### `po` - Purchase Orders (420 rows)
Purchase order headers.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| num | varchar(25) | UNI | PO number |
| vendorId | int | FK→vendor | Vendor |
| statusId | int | FK→postatus | Status |
| dateCreated | datetime | | Created date |
| dateIssued | datetime | | Issued date |
| dateCompleted | datetime | | Completed date |
| buyerId | int | FK→sysuser | Buyer |
| locationGroupId | int | FK→locationgroup | Location group |
| carrierId | int | FK→carrier | Carrier |
| paymentTermsId | int | FK→paymentterms | Payment terms |
| totalTax | decimal(28,9) | | Total tax |
| customFields | json | | Custom field values |

#### `poitem` - Purchase Order Items (977 rows)
Purchase order line items.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| poId | int | FK→po | Parent PO |
| poLineItem | int | | Line number |
| partId | int | FK→part | Part |
| partNum | varchar(70) | | Part number |
| description | varchar(256) | | Description |
| qtyToFulfill | decimal(28,9) | | Quantity to fulfill |
| qtyFulfilled | decimal(28,9) | | Quantity fulfilled |
| unitCost | decimal(28,9) | | Unit cost |
| totalCost | decimal(28,9) | | Total cost |
| statusId | int | FK→poitemstatus | Status |
| typeId | int | FK→poitemtype | Item type |
| dateScheduledFulfillment | datetime | | Scheduled date |
| vendorPartNum | varchar(70) | | Vendor part number |
| customFields | json | | Custom field values |

---

### Manufacturing Tables

#### `bom` - Bill of Materials (1,133 rows)
Bill of Materials definitions.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| num | varchar(70) | UNI | BOM number |
| description | varchar(252) | | Description |
| revision | varchar(31) | | Revision |
| activeFlag | bit(1) | | Is active |
| configurable | bit(1) | | Is configurable |
| estimatedDuration | int | | Estimated duration (minutes) |
| userId | int | FK→sysuser | Owner user |
| customFields | json | | Custom field values |

#### `bomitem` - BOM Components (8,673 rows)
BOM line items/components.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| bomId | int | FK→bom | Parent BOM |
| partId | int | FK→part | Component part |
| description | varchar(256) | | Description |
| quantity | decimal(28,9) | | Quantity required |
| typeId | int | FK→bomitemtype | Item type |
| uomId | int | FK→uom | UOM |
| stage | bit(1) | | Is a stage |
| oneTimeItem | bit(1) | | One-time item (not per unit) |
| customFields | json | | Custom field values |

#### `mo` - Manufacturing Orders (528 rows)
Manufacturing order headers.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| num | varchar(25) | UNI | MO number |
| statusId | int | FK→mostatus | Status |
| soId | int | FK→so | Linked Sales Order |
| locationGroupId | int | FK→locationgroup | Location group |
| dateCreated | datetime | | Created date |
| dateIssued | datetime | | Issued date |
| dateScheduled | datetime | | Scheduled date |
| dateCompleted | datetime | | Completed date |
| userId | int | FK→sysuser | User |
| customFields | json | | Custom field values |

#### `moitem` - Manufacturing Order Items (25,570 rows)
MO line items (both finished goods and raw materials).

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| moId | int | FK→mo | Parent MO |
| bomId | int | FK→bom | BOM used |
| bomItemId | int | FK→bomitem | BOM item reference |
| partId | int | FK→part | Part |
| description | varchar(256) | | Description |
| qtyToFulfill | decimal(28,9) | | Quantity to make/consume |
| qtyFulfilled | decimal(28,9) | | Quantity fulfilled |
| statusId | int | FK→moitemstatus | Status |
| typeId | int | FK→bomitemtype | Item type |
| parentId | int | FK→moitem | Parent item (for hierarchy) |
| soItemId | int | FK→soitem | Linked SO item |
| uomId | int | FK→uom | UOM |

#### `wo` - Work Orders (2,132 rows)
Work orders (individual production tasks).

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| num | varchar(30) | UNI | WO number |
| moItemId | int | FK→moitem | Parent MO item |
| statusId | int | FK→wostatus | Status |
| locationId | int | FK→location | Production location |
| locationGroupId | int | FK→locationgroup | Location group |
| qtyTarget | int | | Target quantity |
| qtyOrdered | int | | Ordered quantity |
| qtyScrapped | int | | Scrapped quantity |
| dateCreated | datetime | | Created date |
| dateScheduled | datetime | | Scheduled date |
| dateStarted | datetime | | Started date |
| dateFinished | datetime | | Finished date |
| cost | decimal(28,9) | | Total cost |
| customerId | int | FK→customer | Customer (if job-specific) |
| customFields | json | | Custom field values |

#### `woitem` - Work Order Items (21,874 rows)
Work order line items (materials consumed).

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| woId | int | FK→wo | Parent WO |
| moItemId | int | FK→moitem | MO item reference |
| partId | int | FK→part | Part consumed |
| description | varchar(256) | | Description |
| qtyTarget | decimal(28,9) | | Target quantity |
| qtyUsed | decimal(28,9) | | Quantity used |
| qtyScrapped | decimal(28,9) | | Quantity scrapped |
| cost | decimal(28,9) | | Cost |
| typeId | int | FK→bomitemtype | Item type |
| uomId | int | FK→uom | UOM |

---

### Inventory Tables

#### `location` - Inventory Locations (6,371 rows)
Warehouse bins/locations.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| name | varchar(30) | | Location name |
| description | varchar(252) | | Description |
| locationGroupId | int | FK→locationgroup | Location group |
| typeId | int | FK→locationtype | Location type |
| activeFlag | bit(1) | | Is active |
| pickable | bit(1) | | Can pick from |
| receivable | bit(1) | | Can receive into |
| countedAsAvailable | bit(1) | | Counts as available |
| defaultCustomerId | int | FK→customer | Default customer (consignment) |
| defaultVendorId | int | FK→vendor | Default vendor (consignment) |
| customFields | json | | Custom field values |

#### `tag` - Inventory Tags (9,290 rows)
Inventory records (quantity of a part at a location).

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | bigint | PRI | Primary key |
| num | bigint | UNI | Tag number |
| partId | int | FK→part | Part |
| locationId | int | FK→location | Location |
| qty | decimal(28,9) | | Quantity on hand |
| qtyCommitted | decimal(28,9) | | Committed quantity |
| typeId | int | FK→tagtype | Tag type |
| woItemId | int | FK→woitem | Work order item (if WIP) |
| dateCreated | datetime | | Created date |
| serializedFlag | bit(1) | | Is serialized |

#### `inventorylog` - Inventory Transaction Log (34,563 rows)
Audit trail of all inventory movements.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | bigint | PRI | Primary key |
| partId | int | FK→part | Part |
| begLocationId | int | FK→location | Beginning location |
| endLocationId | int | FK→location | Ending location |
| begTagNum | bigint | | Beginning tag number |
| endTagNum | bigint | | Ending tag number |
| changeQty | decimal(28,9) | | Quantity changed |
| qtyOnHand | decimal(28,9) | | Resulting qty on hand |
| cost | decimal(28,9) | | Cost |
| typeId | int | FK→inventorylogtype | Transaction type |
| userId | int | FK→sysuser | User |
| eventDate | datetime | | Event date |
| info | varchar(100) | | Additional info |
| locationGroupId | int | FK→locationgroup | Location group |

---

### Picking & Shipping Tables

#### `pick` - Pick Tickets (2,373 rows)
Pick ticket headers.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| statusId | int | FK→pickstatus | Status |
| typeId | int | FK→picktype | Type (Pick/Putaway/Move) |
| locationGroupId | int | FK→locationgroup | Location group |
| priority | int | FK→priority | Priority |
| userId | int | FK→sysuser | Assigned user |

#### `pickitem` - Pick Items (20,281 rows)
Pick ticket line items.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| pickId | int | FK→pick | Parent pick |
| partId | int | FK→part | Part |
| soItemId | int | FK→soitem | SO item (if for SO) |
| poItemId | int | FK→poitem | PO item (if for PO) |
| woItemId | int | FK→woitem | WO item (if for WO) |
| statusId | int | FK→pickitemstatus | Status |
| typeId | int | FK→pickitemtype | Type |
| orderTypeId | int | FK→ordertype | Order type |
| uomId | int | FK→uom | UOM |

#### `ship` - Shipments (186 rows)
Shipment headers.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| soId | int | FK→so | SO (if shipping for SO) |
| poId | int | FK→po | PO (if shipping to vendor) |
| statusId | int | FK→shipstatus | Status |
| carrierId | int | FK→carrier | Carrier |
| carrierServiceId | int | FK→carrierservice | Service level |
| orderTypeId | int | FK→ordertype | Order type |
| locationGroupId | int | FK→locationgroup | Location group |
| shippedBy | int | FK→sysuser | Shipped by user |

#### `shipitem` - Shipped Items (517 rows)
Shipment line items.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| shipId | int | FK→ship | Parent shipment |
| soItemId | int | FK→soitem | SO item |
| poItemId | int | FK→poitem | PO item |
| orderTypeId | int | FK→ordertype | Order type |
| shipCartonId | int | FK→shipcarton | Carton |
| uomId | int | FK→uom | UOM |

#### `receipt` - Receipts (417 rows)
Receiving headers.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| poId | int | FK→po | PO (if receiving for PO) |
| soId | int | FK→so | SO (if RMA) |
| statusId | int | FK→receiptstatus | Status |
| typeId | int | FK→receipttype | Type |
| orderTypeId | int | FK→ordertype | Order type |
| locationGroupId | int | FK→locationgroup | Location group |
| userId | int | FK→sysuser | Received by user |

#### `receiptitem` - Received Items (1,081 rows)
Receipt line items.

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | int | PRI | Primary key |
| receiptId | int | FK→receipt | Parent receipt |
| poItemId | int | FK→poitem | PO item |
| soItemId | int | FK→soitem | SO item (if RMA) |
| partId | int | FK→part | Part |
| statusId | int | FK→receiptitemstatus | Status |
| typeId | int | FK→receiptitemtype | Type |
| orderTypeId | int | FK→ordertype | Order type |
| uomId | int | FK→uom | UOM |

---

## 🔢 Status & Type Lookup Values

### Sales Order Status (`sostatus`)
| ID | Name | Description |
|----|------|-------------|
| 10 | Estimate | Quote/estimate stage |
| 20 | Issued | Issued/open |
| 25 | In Progress | Being processed |
| 60 | Fulfilled | Completely fulfilled |
| 70 | Closed Short | Closed with short shipment |
| 80 | Voided | Voided |
| 85 | Cancelled | Cancelled |
| 90 | Expired | Expired quote |
| 95 | Historical | Historical/archived |

### Sales Order Item Status (`soitemstatus`)
| ID | Name |
|----|------|
| 10 | Entered |
| 11 | Awaiting Build |
| 12 | Building |
| 14 | Built |
| 20 | Picking |
| 30 | Partial |
| 40 | Picked |
| 50 | Fulfilled |
| 60 | Closed Short |
| 70 | Voided |
| 75 | Cancelled |
| 95 | Historical |

### Sales Order Item Type (`soitemtype`)
| ID | Name |
|----|------|
| 10 | Sale |
| 11 | Misc. Sale |
| 12 | Drop Ship |
| 20 | Credit Return |
| 21 | Misc. Credit |
| 30 | Discount Percentage |
| 31 | Discount Amount |
| 40 | Subtotal |
| 50 | Assoc. Price |
| 60 | Shipping |
| 70 | Tax |
| 80 | Kit |
| 90 | Note |

### Purchase Order Status (`postatus`)
| ID | Name |
|----|------|
| 2 | For Calendar |
| 10 | Bid Request |
| 15 | Pending Approval |
| 20 | Issued |
| 30 | Picking |
| 40 | Partial |
| 50 | Picked |
| 55 | Shipped |
| 60 | Fulfilled |
| 70 | Closed Short |
| 80 | Void |
| 95 | Historical |

### Purchase Order Item Status (`poitemstatus`)
| ID | Name |
|----|------|
| 5 | All Open |
| 10 | Entered |
| 20 | Picking |
| 30 | Partial |
| 40 | Picked |
| 45 | Shipped |
| 50 | Fulfilled |
| 60 | Closed Short |
| 70 | Void |
| 95 | Historical |

### Purchase Order Item Type (`poitemtype`)
| ID | Name |
|----|------|
| 10 | Purchase |
| 11 | Misc. Purchase |
| 20 | Credit Return |
| 21 | Misc. Credit |
| 30 | Out Sourced |
| 40 | Shipping |

### Manufacturing Order Status (`mostatus`)
| ID | Name |
|----|------|
| 10 | Entered |
| 20 | Issued |
| 50 | Partial |
| 60 | Fulfilled |
| 70 | Closed Short |
| 80 | Void |

### Manufacturing Order Item Status (`moitemstatus`)
| ID | Name |
|----|------|
| 10 | Entered |
| 20 | Picking |
| 30 | Working |
| 40 | Partial |
| 50 | Fulfilled |
| 60 | Closed Short |
| 70 | Void |

### Work Order Status (`wostatus`)
| ID | Name |
|----|------|
| 10 | Entered |
| 30 | Started |
| 40 | Fulfilled |

### Part Type (`parttype`)
| ID | Name | Description |
|----|------|-------------|
| 10 | Inventory | Stocked inventory items |
| 20 | Service | Service items |
| 21 | Labor | Labor items |
| 22 | Overhead | Overhead costs |
| 30 | Non-Inventory | Non-inventory items |
| 40 | Internal Use | Internal use items |
| 50 | Capital Equipment | Capital equipment |
| 60 | Shipping | Shipping charges |
| 70 | Tax | Tax items |
| 80 | Misc | Miscellaneous |

### BOM Item Type (`bomitemtype`)
| ID | Name | Description |
|----|------|-------------|
| 10 | Finished Good | Output of the BOM |
| 20 | Raw Good | Input material |
| 30 | Repair Raw Good | Repair input |
| 31 | Repair Finished Good | Repair output |
| 40 | Note | Note/instruction |
| 50 | Bill of Materials | Nested BOM |

### Location Type (`locationtype`)
| ID | Name |
|----|------|
| 10 | Stock |
| 20 | Shipping |
| 30 | Receiving |
| 40 | Vendor |
| 50 | Inspection |
| 60 | Locked |
| 70 | Store Front |
| 80 | Manufacturing |
| 90 | Picking |
| 100 | In Transit |
| 110 | Consignment |

### Customer Status (`customerstatus`)
| ID | Name |
|----|------|
| 10 | Normal |
| 20 | Preferred |
| 30 | Hold Sales |
| 40 | Hold Shipment |
| 50 | Hold All |

### Vendor Status (`vendorstatus`)
| ID | Name |
|----|------|
| 10 | Normal |
| 20 | Preferred |
| 30 | Hold PO |
| 40 | Hold Receipt |
| 50 | Hold All |

### Pick Status (`pickstatus`)
| ID | Name |
|----|------|
| 10 | Entered |
| 20 | Started |
| 30 | Committed |
| 40 | Finished |

### Pick Type (`picktype`)
| ID | Name |
|----|------|
| 10 | Pick |
| 20 | Putaway |
| 30 | Move |

### Ship Status (`shipstatus`)
| ID | Name |
|----|------|
| 10 | Entered |
| 20 | Packed |
| 30 | Shipped |
| 40 | Cancelled |

### Receipt Status (`receiptstatus`)
| ID | Name |
|----|------|
| 10 | Entered |
| 20 | Reconciled |
| 30 | Received |
| 40 | Fulfilled |

### Tag Type (`tagtype`)
| ID | Name |
|----|------|
| 10 | Location |
| 20 | Parent |
| 30 | Child |
| 40 | Virtual |

### Inventory Log Type (`inventorylogtype`)
| ID | Code | Description |
|----|------|-------------|
| 1 | undefined | Undefined |
| 10 | rcv | Receive |
| 15 | can | Cancel |
| 20 | shp | Ship |
| 30 | xfr | Transfer |
| 40 | yld | Yield |
| 50 | csm | Consume |
| 60 | adj | Adjust |
| 64 | adj:inc | Adjust Increase |
| 65 | adj:dec | Adjust Decrease |
| 67 | adj:scp | Adjust Scrap |
| 68 | adj:cyc | Adjust Cycle Count |
| 69 | adj:uom | Adjust UOM |
| 70 | adj:cog | Adjust COGS |
| 71 | adj:lnd | Adjust Landed Cost |
| 72 | adj:trk | Adjust Tracking |
| 73 | adj:etrk | Adjust End Tracking |
| 74 | adj:dtrk | Adjust Delete Tracking |
| 80 | cm | Commit |
| 90 | vd:Shp | Void Ship |

### Order Type (`ordertype`)
| ID | Name |
|----|------|
| 1 | None |
| 10 | PO |
| 20 | SO |
| 30 | WO |
| 40 | TO |

### UOM Type (`uomtype`)
| ID | Name |
|----|------|
| 1 | Count |
| 2 | Weight |
| 3 | Length |
| 4 | Area |
| 5 | Volume |
| 6 | Time |

### Account Type (`accounttype`)
| ID | Name |
|----|------|
| 10 | Retail |
| 20 | Wholesale |
| 30 | Internet |

---

## 🔍 Useful Views

The database includes several pre-built views:

| View Name | Rows | Description |
|-----------|------|-------------|
| `qohview` | 9,290 | Quantity on hand by tag |
| `qtyonhand` | 2,274 | Current on-hand quantities |
| `qtycommitted` | 2,276 | Committed quantities |
| `qtyallocated` | 605 | Allocated quantities |
| `qtyonorder` | 303 | Quantities on order |
| `qtyinventory` | 2,405 | Inventory summary |
| `qtyinventorytotals` | 2,405 | Inventory totals |
| `v_inventorytotals` | 2,405 | Inventory totals view |
| `v_all_bom_details` | 36,372 | Exploded BOM details |
| `v_available_to_build` | 8,667 | Available to build quantities |
| `v_bom_cost` | 7,791 | BOM costs |
| `v_wip` | 96 | Work in progress |
| `v_invoices` | 813 | Invoice view |
| `v_invoice_revenue` | 3 | Invoice revenue summary |
| `customercontactview` | 248 | Customer contacts |
| `vendorcontactview` | 519 | Vendor contacts |
| `womoview` | 2,132 | WO/MO relationship view |
| `nextorderview` | 638 | Next order numbers |

---

## 📝 Common Query Examples

### Get Active Parts with Inventory
```sql
SELECT p.num, p.description, SUM(t.qty) as qty_on_hand
FROM part p
JOIN tag t ON t.partId = p.id
JOIN location l ON t.locationId = l.id
WHERE p.activeFlag = 1
  AND l.countedAsAvailable = 1
  AND t.qty > 0
GROUP BY p.id, p.num, p.description
ORDER BY p.num;
```

### Get Open Sales Orders with Items
```sql
SELECT so.num as so_num, so.dateCreated, c.name as customer,
       sos.name as status, soi.productNum, soi.description,
       soi.qtyOrdered, soi.qtyFulfilled, soi.unitPrice
FROM so
JOIN customer c ON so.customerId = c.id
JOIN sostatus sos ON so.statusId = sos.id
JOIN soitem soi ON soi.soId = so.id
WHERE so.statusId IN (20, 25) -- Issued, In Progress
ORDER BY so.dateCreated DESC;
```

### Get Open Purchase Orders with Items
```sql
SELECT po.num as po_num, po.dateCreated, v.name as vendor,
       pos.name as status, poi.partNum, poi.description,
       poi.qtyToFulfill, poi.qtyFulfilled, poi.unitCost
FROM po
JOIN vendor v ON po.vendorId = v.id
JOIN postatus pos ON po.statusId = pos.id
JOIN poitem poi ON poi.poId = po.id
WHERE po.statusId IN (20, 30, 40) -- Issued, Picking, Partial
ORDER BY po.dateCreated DESC;
```

### Get Manufacturing Orders with Work Orders
```sql
SELECT mo.num as mo_num, mo.dateScheduled, mos.name as mo_status,
       wo.num as wo_num, wos.name as wo_status,
       p.num as part_num, p.description,
       moitem.qtyToFulfill, moitem.qtyFulfilled
FROM mo
JOIN mostatus mos ON mo.statusId = mos.id
JOIN moitem ON moitem.moId = mo.id
JOIN part p ON moitem.partId = p.id
LEFT JOIN wo ON wo.moItemId = moitem.id
LEFT JOIN wostatus wos ON wo.statusId = wos.id
WHERE mo.statusId IN (10, 20, 50) -- Entered, Issued, Partial
  AND moitem.typeId = 10 -- Finished Good
ORDER BY mo.dateScheduled;
```

### Get BOM Structure (Exploded)
```sql
SELECT b.num as bom_num, b.description as bom_desc,
       p.num as component_part, p.description as component_desc,
       bi.quantity, u.code as uom,
       bit.name as item_type
FROM bom b
JOIN bomitem bi ON bi.bomId = b.id
JOIN part p ON bi.partId = p.id
JOIN uom u ON bi.uomId = u.id
JOIN bomitemtype bit ON bi.typeId = bit.id
WHERE b.activeFlag = 1
ORDER BY b.num, bi.id;
```

### Get Inventory by Location
```sql
SELECT lg.name as location_group, l.name as location,
       p.num as part_num, p.description,
       t.qty as qty_on_hand, t.qtyCommitted
FROM tag t
JOIN location l ON t.locationId = l.id
JOIN locationgroup lg ON l.locationGroupId = lg.id
JOIN part p ON t.partId = p.id
WHERE t.qty > 0
ORDER BY lg.name, l.name, p.num;
```

### Get Inventory Transactions
```sql
SELECT il.eventDate, ilt.name as trans_type,
       p.num as part_num, p.description,
       bl.name as from_location, el.name as to_location,
       il.changeQty, il.qtyOnHand, il.cost,
       u.userName as user
FROM inventorylog il
JOIN inventorylogtype ilt ON il.typeId = ilt.id
JOIN part p ON il.partId = p.id
JOIN location bl ON il.begLocationId = bl.id
JOIN location el ON il.endLocationId = el.id
JOIN sysuser u ON il.userId = u.id
WHERE il.eventDate >= DATE_SUB(NOW(), INTERVAL 30 DAY)
ORDER BY il.eventDate DESC;
```

### Get Vendor Parts with Costs
```sql
SELECT v.name as vendor, p.num as part_num, p.description,
       vp.vendorPartNumber, vp.cost, vp.leadTime,
       u.code as uom
FROM vendorparts vp
JOIN vendor v ON vp.vendorId = v.id
JOIN part p ON vp.partId = p.id
JOIN uom u ON vp.uomId = u.id
WHERE v.activeFlag = 1
ORDER BY v.name, p.num;
```

### Get Customer Sales History
```sql
SELECT c.name as customer, so.num as so_num,
       so.dateCreated, sos.name as status,
       so.totalPrice, so.totalTax
FROM so
JOIN customer c ON so.customerId = c.id
JOIN sostatus sos ON so.statusId = sos.id
ORDER BY c.name, so.dateCreated DESC;
```

---

## 📊 Data Statistics Summary

| Category | Table | Row Count |
|----------|-------|-----------|
| **Master Data** | part | 6,278 |
| | product | 1,332 |
| | customer | 248 |
| | vendor | 519 |
| | location | 6,371 |
| **Sales** | so | 286 |
| | soitem | 1,313 |
| | ship | 186 |
| | shipitem | 517 |
| **Purchasing** | po | 420 |
| | poitem | 977 |
| | receipt | 417 |
| | receiptitem | 1,081 |
| **Manufacturing** | bom | 1,133 |
| | bomitem | 8,673 |
| | mo | 528 |
| | moitem | 25,570 |
| | wo | 2,132 |
| | woitem | 21,874 |
| **Inventory** | tag | 9,290 |
| | inventorylog | 34,563 |
| | costlayer | 7,551 |
| **Picking** | pick | 2,373 |
| | pickitem | 20,281 |

---

## 🔐 Audit Tables

Tables ending in `_aud` are **Hibernate Envers audit tables** that track historical changes:
- They reference `revinfo` table for revision metadata
- Each row represents a historical version of a record
- Useful for tracking who changed what and when

Key audit tables:
- `part_aud` (19,802 rows)
- `product_aud` (3,104 rows)
- `so_aud` (2,519 rows)
- `soitem_aud` (8,176 rows)
- `moitem_aud` (88,563 rows)
- `woitem_aud` (46,063 rows)

---

## 📦 Custom Tables (Non-Standard Fishbowl)

These tables appear to be custom additions:

| Table | Rows | Description |
|-------|------|-------------|
| `pcmrp_bom_import` | 54,002 | PCMRP BOM import data |
| `zz_pcmrp_bom` | 57,146 | PCMRP BOM data |
| `zz_pcmrp_partmast` | 32,945 | PCMRP part master |
| `zz_pcmrp_purchase` | 110,719 | PCMRP purchase data |
| `zz_avgcost` | 1,996 | Average cost calculations |
| `zz_sales` | 24,614 | Sales data extract |
| `closed_so` | 21 | Closed SO tracking |
| `z_userlog` | 271 | User activity log |

---

## 🔧 Notes for Queries

1. **Status Filters**: Always filter by status to get meaningful results
2. **Active Flags**: Most master tables have `activeFlag` - use it
3. **Location Group**: Filter by `locationGroupId` when needed
4. **Date Fields**: 
   - `dateCreated` - Record creation
   - `dateLastModified` - Last update
   - `dateIssued` - When order was issued
   - `dateCompleted` - When order completed
5. **Custom Fields**: JSON column for custom field values
6. **Audit Trail**: Use `_aud` tables + `revinfo` for history

---

## 📊 Supply Chain KPI: Shortage Analysis

### Shortage Categories

When analyzing picking shortages (`pickitem.statusId = 5`), categorize them into:

| Category | Definition | Action Required |
|----------|------------|-----------------|
| **TRUE Material Shortage** | No inventory in available locations AND no WIP inventory | Create PO or expedite existing orders |
| **WIP Shortage** | No available inventory BUT material exists in Manufacturing/WO | Track WO completion - no procurement needed |
| **Committed Elsewhere** | Available inventory exists but committed to other orders | May need to reprioritize |

### Key Tables for Shortage Analysis

- `pickitem` - Pick line items, status 5 = Short
- `pick` - Pick headers (for dates, aging)
- `tag` - Inventory records (qty by part/location)
- `location` - Location details (typeId 80 = Manufacturing/WIP)
- `woitem` - Work order items (tag.woItemId links to this)

### Shortage Logic

```sql
-- TRUE SHORTAGE: No available stock AND no WIP
WHEN available_qty <= 0 AND wip_qty <= 0 THEN 'TRUE_SHORTAGE'

-- WIP SHORTAGE: No available stock BUT has WIP
WHEN available_qty <= 0 AND wip_qty > 0 THEN 'WIP_SHORTAGE'

-- COMMITTED ELSEWHERE: Has available stock
ELSE 'COMMITTED_ELSEWHERE'
```

### Related Files

- `shortage_kpi_dashboard.py` - Python dashboard script
- `shortage_kpi_queries.sql` - SQL queries for reporting

---

## 📚 External References

- [Fishbowl Database Tables Documentation](https://fishbowlhelp.com/files/database/tables)
- [Fishbowl Help Center](https://fishbowlhelp.com)

---

*This document is a reference for querying the MetrohmSpectro Fishbowl database. Always test queries in a safe environment before running on production data.*
