import test from 'node:test'
import assert from 'node:assert/strict'

import type { Note } from '../types'
import {
  chooseCardRatioObject,
  chooseCompositeCardVisualObject,
  cleanDisplayTitle,
  collectLinkChips,
  collectSourceChips,
  getCompositePreviewObjects,
  getNoteDisplayTitle,
  getNoteDetailModel,
  getSavedDateLabel,
  getTelegramCardModel,
  isCardVisualObjectType,
  isRedundantTextTitle,
  truncateMarkdownInline,
} from './noteCardPresentation.ts'

function noteObject(overrides: Partial<Note['objects'][number]>): Note['objects'][number] {
  return {
    id: overrides.id ?? 'object-1',
    type: overrides.type ?? 'text',
    content: overrides.content ?? '',
    createdAt: overrides.createdAt ?? '2026-05-01T10:00:00Z',
    ...overrides,
  }
}

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

test('telegram card model keeps source, caption, and media together', () => {
  assert.deepEqual(getTelegramCardModel(telegramNote), {
    sourceLabel: 'Telegram',
    originLabel: 'Бэкдор',
    caption: '⚡️ Забираем лучшие настройки OBS',
    media: telegramNote.objects,
    itemCount: 2,
  })
})

test('telegram detail view uses the shared stream model with source context', () => {
  const model = getNoteDetailModel(telegramNote)

  assert.equal(model.source?.provider, 'telegram')
  assert.equal(model.source?.providerLabel, 'Telegram')
  assert.equal(model.source?.originLabel, 'Бэкдор')
  assert.deepEqual(model.objects.map(item => item.object.id), ['photo-1', 'photo-2'])
  assert.deepEqual(model.objects.map(item => item.childHref), [null, null])
  assert.deepEqual(model.objects.map(item => item.viewerNoteId), ['note-1', 'note-1'])
})

test('collection detail model keeps child note navigation explicit', () => {
  const model = getNoteDetailModel({
    ...telegramNote,
    source: null,
    objects: [
      noteObject({ id: 'child-note-1', slug: 'child-slug', type: 'text', content: 'child text' }),
      noteObject({ id: 'inline-image', type: 'image', content: '/image.jpg' }),
    ],
  })

  assert.deepEqual(model.objects.map(item => item.childHref), ['/notes/child-slug', null])
  assert.deepEqual(model.objects.map(item => item.viewerNoteId), ['child-note-1', 'note-1'])
})

test('collection detail model uses child note id for flattened child assets', () => {
  const model = getNoteDetailModel({
    ...telegramNote,
    source: null,
    objects: [
      noteObject({
        id: 'asset-1',
        slug: 'child-slug',
        noteId: 'child-note-1',
        type: 'image',
        content: '/api/v1/notes/child-slug/asset/asset-1',
      }),
    ],
  })

  assert.equal(model.objects[0].childHref, '/notes/child-slug')
  assert.equal(model.objects[0].viewerNoteId, 'child-note-1')
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

test('link chips expose domains for card metadata row', () => {
  const note: Note = {
    ...telegramNote,
    type: 'composite',
    title: 'Research bundle',
    objects: [
      noteObject({
        id: 'link-1',
        type: 'link',
        content: 'https://habr.com/ru/articles/551948/',
      }),
      noteObject({
        id: 'text-1',
        type: 'text',
        content: 'Saved context',
      }),
    ],
  }

  assert.deepEqual(collectLinkChips(note), [{
    key: 'link-1',
    url: 'https://habr.com/ru/articles/551948/',
    label: 'habr.com',
    title: 'https://habr.com/ru/articles/551948/',
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

test('card visual object types include media and files but not text', () => {
  assert.equal(isCardVisualObjectType('image'), true)
  assert.equal(isCardVisualObjectType('video'), true)
  assert.equal(isCardVisualObjectType('audio'), true)
  assert.equal(isCardVisualObjectType('document'), true)
  assert.equal(isCardVisualObjectType('link'), true)
  assert.equal(isCardVisualObjectType('text'), false)
})

test('ratio object prefers the first visual object with known dimensions', () => {
  const video = noteObject({ id: 'video-1', type: 'video', content: '/video.mp4' })
  const image = noteObject({
    id: 'image-1',
    type: 'image',
    content: '/image.jpg',
    visualWidth: 1280,
    visualHeight: 720,
  })

  assert.equal(chooseCardRatioObject([video, image]), image)
})

test('composite card visual object keeps media placeholders eligible', () => {
  const text = noteObject({ id: 'text-1', type: 'text', content: 'caption' })
  const video = noteObject({ id: 'video-1', type: 'video', content: '/video.mp4' })
  const audio = noteObject({ id: 'audio-1', type: 'audio', content: '/audio.mp3' })
  const document = noteObject({ id: 'doc-1', type: 'document', content: '/doc.pdf' })

  assert.equal(chooseCompositeCardVisualObject([text, video]), video)
  assert.equal(chooseCompositeCardVisualObject([text, audio]), audio)
  assert.equal(chooseCompositeCardVisualObject([text, document]), document)
})

test('composite preview objects keep multiple media in note order', () => {
  const text = noteObject({ id: 'text-1', type: 'text', content: 'caption' })
  const video = noteObject({ id: 'video-1', type: 'video', content: '/video.mp4' })
  const image = noteObject({ id: 'image-1', type: 'image', content: '/image.jpg' })
  const audio = noteObject({ id: 'audio-1', type: 'audio', content: '/audio.mp3' })

  assert.deepEqual(
    getCompositePreviewObjects([text, video, image, audio]).map(obj => obj.id),
    ['video-1', 'image-1', 'audio-1'],
  )
})
