// รันด้วย: node --test src/hooks/cartRules.test.mjs   (ใช้ test runner ของ node เอง ไม่ต้องลง framework)
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { bundleSkippedNames, isBundleItemAvailable, mergeCartItem } from './cartRules.js'

const wire = { id: 'w', item_type: 'consumable', quantity_available: 500 }
const pc = { id: 'p', item_type: 'durable', quantity_available: 1 }
const grouped_ap = { id: 'ap', item_type: 'durable', quantity_available: 12 } // การ์ดยุบรวมหลายหน่วยรุ่นเดียวกัน

test('ของใหม่ถูกเพิ่มเข้าตะกร้า', () => {
  assert.deepEqual(mergeCartItem([], wire, 100), [{ equipment: wire, quantity: 100 }])
})

test('ของซ้ำต้องบวกจำนวนรวมกัน ไม่ใช่หายเงียบ', () => {
  const cart = mergeCartItem(mergeCartItem([], wire, 100), wire, 50)
  assert.equal(cart.length, 1)
  assert.equal(cart[0].quantity, 150)
})

test('บวกแล้วต้องไม่เกินของคงเหลือ', () => {
  const cart = mergeCartItem([{ equipment: wire, quantity: 480 }], wire, 100)
  assert.equal(cart[0].quantity, 500)
})

test('ครุภัณฑ์ที่เหลือหน่วยเดียวยังล็อกที่ 1 (ไม่ได้อิง item_type แล้ว แต่ quantity_available ยังคุมพฤติกรรมเดิมได้)', () => {
  const cart = mergeCartItem([{ equipment: pc, quantity: 1 }], pc, 1)
  assert.equal(cart[0].quantity, 1)
})

test('ครุภัณฑ์รุ่นที่ยุบรวมหลายหน่วยขอเกิน 1 ได้ (ไม่ล็อกตาม item_type อีกต่อไป)', () => {
  const cart = mergeCartItem([{ equipment: grouped_ap, quantity: 1 }], grouped_ap, 2)
  assert.equal(cart[0].quantity, 3)
})

test('ของในชุดที่ยืมไม่ได้ต้องถูกข้าม', () => {
  assert.equal(isBundleItemAvailable({ is_borrowable: true, quantity_available: 3 }), true)
  assert.equal(isBundleItemAvailable({ is_borrowable: false, quantity_available: 3 }), false)
  assert.equal(isBundleItemAvailable({ is_borrowable: true, quantity_available: 0 }), false)
})

test('bundleSkippedNames รายงานของที่ยืมไม่ได้ตอนนี้ ไม่รวมตัวกระตุ้น', () => {
  const bundle = {
    trigger_equipment_id: 'trigger',
    items: [
      { equipment_id: 'trigger', equipment_name: 'ตัวกระตุ้น', is_borrowable: true, quantity_available: 5 },
      { equipment_id: 'a', equipment_name: 'สายUSB-C', is_borrowable: true, quantity_available: 0 },
      { equipment_id: 'b', equipment_name: 'เมาส์', is_borrowable: true, quantity_available: 4 },
    ],
  }
  assert.deepEqual(bundleSkippedNames(bundle), ['สายUSB-C'])
})

test('bundleSkippedNames ว่างเปล่าเมื่อของในชุดยืมได้ครบ', () => {
  const bundle = {
    trigger_equipment_id: 'trigger',
    items: [{ equipment_id: 'a', equipment_name: 'เมาส์', is_borrowable: true, quantity_available: 4 }],
  }
  assert.deepEqual(bundleSkippedNames(bundle), [])
})
