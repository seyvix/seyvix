import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
import { partitionUploadFiles } from './uploadGuard.ts'

function makeFile(name: string): File {
  return new File([new Uint8Array([0])], name, { type: 'application/octet-stream' })
}

describe('partitionUploadFiles', () => {
  test('lets supported files through', () => {
    const { accepted, rejected } = partitionUploadFiles([
      makeFile('report.docx'),
      makeFile('photo.png'),
      makeFile('slides.pptx'),
    ])
    assert.equal(accepted.length, 3)
    assert.equal(rejected.length, 0)
  })

  test('rejects iWork extensions case-insensitively', () => {
    const { accepted, rejected } = partitionUploadFiles([
      makeFile('deck.key'),
      makeFile('Deck.KEY'),
      makeFile('letter.pages'),
      makeFile('budget.Numbers'),
    ])
    assert.equal(accepted.length, 0)
    assert.equal(rejected.length, 4)
    for (const item of rejected) {
      assert.ok(item.reason.includes('PDF'))
      assert.ok(item.reason.includes('Keynote') || item.reason.includes('Pages') || item.reason.includes('Numbers'))
    }
  })

  test('splits a mixed batch', () => {
    const { accepted, rejected } = partitionUploadFiles([
      makeFile('one.key'),
      makeFile('two.pdf'),
    ])
    assert.equal(accepted.length, 1)
    assert.equal(accepted[0].name, 'two.pdf')
    assert.equal(rejected.length, 1)
    assert.equal(rejected[0].file.name, 'one.key')
  })
})
