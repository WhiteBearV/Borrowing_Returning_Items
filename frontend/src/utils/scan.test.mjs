import assert from 'node:assert/strict'
import { parseScan } from './scan.js'

const id = '1fbce86d-58f5-429f-863f-b6ca5653fd87'
assert.deepEqual(parseScan(`https://172.16.46.130/equipment/${id}`), { equipmentId: id })
assert.deepEqual(parseScan(`http://localhost:5173/equipment/${id.toUpperCase()}?x=1`), { equipmentId: id })
assert.deepEqual(parseScan('  CON-WIRE-001 \n'), { code: 'CON-WIRE-001' })
assert.deepEqual(parseScan(`https://x/equipment/${id}extra`), { code: `https://x/equipment/${id}extra` })
assert.equal(parseScan('   '), null)
console.log('scan ok')
