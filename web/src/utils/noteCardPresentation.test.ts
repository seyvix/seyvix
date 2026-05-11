import test from 'node:test'
import assert from 'node:assert/strict'

import type { Note } from '../types'
import { collectSourceChips, getTelegramCardModel } from './noteCardPresentation.ts'

const telegramNote: Note = {
  id: 'note-1',
  slug: 'telegram-post',
  type: 'collection',
  title: '**Топ-****7**** книг',
  cover: null,
  tags: [],
  folderId: null,
  createdAt: '2026-05-01T10:00:00Z',
  updatedAt: '2026-05-01T10:00:00Z',
  source: {
    provider: 'telegram',
    providerLabel: 'Telegram',
    externalId: 'telegram:142',
    origin: { title: 'Бэкдор', username: 'whackdoor' },
  },
  objects: [
    {
      id: 'photo-1',
      type: 'image',
      content: '/api/v1/assets/photo-1',
      caption: '{{tg_emoji:5280586677532774817|⚡️}} Забираем лучшие настройки OBS',
      imageWidth: 1280,
      imageHeight: 763,
      createdAt: '2026-05-01T10:00:00Z',
    },
    {
      id: 'photo-2',
      type: 'image',
      content: '/api/v1/assets/photo-2',
      imageWidth: 1280,
      imageHeight: 851,
      createdAt: '2026-05-01T10:00:00Z',
    },
  ],
}

test('telegram collection is presented as one post with source, caption, and media', () => {
  assert.deepEqual(getTelegramCardModel(telegramNote), {
    sourceLabel: 'Telegram',
    originLabel: 'Бэкдор',
    caption: '⚡️ Забираем лучшие настройки OBS',
    media: telegramNote.objects,
    itemCount: 2,
  })
})

test('regular collections do not use telegram presentation', () => {
  assert.equal(getTelegramCardModel({
    ...telegramNote,
    source: { provider: 'browser', providerLabel: 'Browser', externalId: 'browser:1' },
  }), null)
})

test('source chips collapse same telegram origin into one readable chip', () => {
  assert.deepEqual(collectSourceChips(telegramNote), [{
    key: 'telegram:Бэкдор',
    providerLabel: 'Telegram',
    originLabel: 'Бэкдор',
    title: 'Telegram: Бэкдор',
  }])
})
