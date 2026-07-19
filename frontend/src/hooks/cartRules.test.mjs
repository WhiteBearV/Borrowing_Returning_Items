// รันด้วย: node --test src/hooks/cartRules.test.mjs   (ใช้ test runner ของ node เอง ไม่ต้องลง framework)
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { isBundleItemAvailable, mergeCartItem } from './cartRules.js'

const wire = { id: 'w', item_type: 'consumable', quantity_available: 500 }
const pc = { id: 'p', item_type: 'durable', quantity_available: 1 }

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

test('ครุภัณฑ์ซ้ำไม่บวกเพิ่ม (ยืมได้ทีละตัว)', () => {
  const cart = mergeCartItem([{ equipment: pc, quantity: 1 }], pc, 1)
  assert.equal(cart[0].quantity, 1)
})

test('ของในชุดที่ยืมไม่ได้ต้องถูกข้าม', () => {
  assert.equal(isBundleItemAvailable({ is_borrowable: true, quantity_available: 3 }), true)
  assert.equal(isBundleItemAvailable({ is_borrowable: false, quantity_available: 3 }), false)
  assert.equal(isBundleItemAvailable({ is_borrowable: true, quantity_available: 0 }), false)
})
