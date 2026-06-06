import test from 'node:test'
import assert from 'node:assert/strict'

import type { Note } from '../types'
import {
  cleanDisplayTitle,
  collectSourceChips,
  getNoteDisplayTitle,
  getSavedDateLabel,
  getTelegramCardModel,
  isRedundantTextTitle,
  truncateMarkdownInline,
} from './noteCardPresentation.ts'

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

test('saved date label uses relative labels for recent notes', () => {
  const now = new Date('2026-05-19T12:00:00+03:00')

  assert.equal(getSavedDateLabel('2026-05-19T08:00:00+03:00', now), 'Сегодня')
  assert.equal(getSavedDateLabel('2026-05-18T23:00:00+03:00', now), 'Вчера')
  assert.equal(getSavedDateLabel('2026-05-16T12:00:00+03:00', now), '3 дн. назад')
  assert.equal(getSavedDateLabel('2026-05-01T12:00:00+03:00', now), '1 мая')
})

test('display titles strip markdown and telegram custom emoji markers', () => {
  assert.equal(
    cleanDisplayTitle('{{tg_emoji:5296452815005185363|⚡}} **За слово «обезьяна»**'),
    'За слово «обезьяна»',
  )
  assert.equal(cleanDisplayTitle('**Последнее время я всё больше углубляюсь в музыку.**'), 'Последнее время я всё больше углубляюсь в музыку.')
})

test('redundant text title is hidden when it duplicates the note body start', () => {
  assert.equal(isRedundantTextTitle('Короткая заметка', 'Короткая заметка'), true)
  assert.equal(isRedundantTextTitle('Короткая заметка', '**Короткая заметка** и продолжение'), true)
  assert.equal(isRedundantTextTitle('Отдельный заголовок', 'Совсем другой текст'), false)
})

test('telegram transport filenames are hidden as display titles', () => {
  assert.equal(
    getNoteDisplayTitle({
      ...telegramNote,
      title: 'telegram-photo',
      type: 'simple',
      objects: [telegramNote.objects[0]],
    }),
    null,
  )
})

test('truncated inline markdown closes open formatting markers', () => {
  assert.equal(
    truncateMarkdownInline('**За слово «обезьяна» в РФ могут ОШТРАФОВАТЬ** на сумму', 32),
    '**За слово «обезьяна» в РФ могут**...',
  )
})
