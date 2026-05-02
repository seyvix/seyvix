import type { Note } from '../../types'

export const noteFixtures: Note[] = [
  // sc1 · Event: cancelable property
  {
    id: 'sc1',
    slug: 'mdn-event-cancelable',
    type: 'composite',
    title: 'Event: cancelable — MDN',
    cover: null,
    tags: [{ id: 'sc1-mdn', name: 'mdn' }, { id: 'sc1-api', name: 'web-api' }, { id: 'sc1-js', name: 'js' }],
    folderId: 'f4',
    objects: [
      { id: 'sc1a', type: 'image', content: '/1.png', createdAt: '2026-04-24T15:40:00Z' },
      { id: 'sc1b', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/API/Event/cancelable', createdAt: '2026-04-24T15:40:00Z' },
    ],
    createdAt: '2026-04-24T15:40:00Z',
    updatedAt: '2026-04-24T15:40:00Z',
  },

  // sc2 · Event: target property
  {
    id: 'sc2',
    slug: 'mdn-event-target',
    type: 'composite',
    title: 'Event: target — MDN',
    cover: null,
    tags: [{ id: 'sc2-mdn', name: 'mdn' }, { id: 'sc2-api', name: 'web-api' }, { id: 'sc2-js', name: 'js' }],
    folderId: 'f4',
    objects: [
      { id: 'sc2a', type: 'image', content: '/2.png', createdAt: '2026-04-24T15:40:00Z' },
      { id: 'sc2b', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/API/Event/target', createdAt: '2026-04-24T15:40:00Z' },
    ],
    createdAt: '2026-04-24T15:40:00Z',
    updatedAt: '2026-04-24T15:40:00Z',
  },

  // sc3 · AbstractRange
  {
    id: 'sc3',
    slug: 'mdn-abstract-range',
    type: 'composite',
    title: 'AbstractRange — MDN',
    cover: null,
    tags: [{ id: 'sc3-mdn', name: 'mdn' }, { id: 'sc3-api', name: 'web-api' }, { id: 'sc3-html', name: 'html' }],
    folderId: 'f4',
    objects: [
      { id: 'sc3a', type: 'image', content: '/3.png', createdAt: '2026-04-24T15:41:00Z' },
      { id: 'sc3b', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/API/AbstractRange', createdAt: '2026-04-24T15:41:00Z' },
    ],
    createdAt: '2026-04-24T15:41:00Z',
    updatedAt: '2026-04-24T15:41:00Z',
  },

  // sc4 · StaticRange
  {
    id: 'sc4',
    slug: 'mdn-static-range',
    type: 'composite',
    title: 'StaticRange — MDN',
    cover: null,
    tags: [{ id: 'sc4-mdn', name: 'mdn' }, { id: 'sc4-api', name: 'web-api' }, { id: 'sc4-html', name: 'html' }],
    folderId: 'f4',
    objects: [
      { id: 'sc4a', type: 'image', content: '/4.png', createdAt: '2026-04-24T15:41:00Z' },
      { id: 'sc4b', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/API/StaticRange', createdAt: '2026-04-24T15:41:00Z' },
    ],
    createdAt: '2026-04-24T15:41:00Z',
    updatedAt: '2026-04-24T15:41:00Z',
  },

  // sc5 · Anatomy of the DOM
  {
    id: 'sc5',
    slug: 'mdn-dom-anatomy',
    type: 'composite',
    title: 'Anatomy of the DOM — MDN',
    cover: null,
    tags: [{ id: 'sc5-mdn', name: 'mdn' }, { id: 'sc5-api', name: 'web-api' }, { id: 'sc5-html', name: 'html' }],
    folderId: 'f4',
    objects: [
      { id: 'sc5a', type: 'image', content: '/5.png', createdAt: '2026-04-24T15:42:00Z' },
      { id: 'sc5b', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/API/Document_Object_Model/Anatomy_of_the_DOM', createdAt: '2026-04-24T15:42:00Z' },
    ],
    createdAt: '2026-04-24T15:42:00Z',
    updatedAt: '2026-04-24T15:42:00Z',
  },

  // sc6 · CDATASection
  {
    id: 'sc6',
    slug: 'mdn-cdata-section',
    type: 'composite',
    title: 'CDATASection — MDN',
    cover: null,
    tags: [{ id: 'sc6-mdn', name: 'mdn' }, { id: 'sc6-api', name: 'web-api' }, { id: 'sc6-html', name: 'html' }],
    folderId: 'f4',
    objects: [
      { id: 'sc6a', type: 'image', content: '/6.png', createdAt: '2026-04-24T15:42:00Z' },
      { id: 'sc6b', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/API/CDATASection', createdAt: '2026-04-24T15:42:00Z' },
    ],
    createdAt: '2026-04-24T15:42:00Z',
    updatedAt: '2026-04-24T15:42:00Z',
  },

  // ─── MDN-заметки ───────────────────────────────────────────────────────────

  // 1 · CSS Flexbox — composite
  {
    id: '1',
    slug: 'mdn-css-flexbox',
    type: 'composite',
    title: 'CSS Flexbox — MDN',
    cover: null,
    tags: [{ id: '1-mdn', name: 'mdn' }, { id: '1-css', name: 'css' }, { id: '1-fe', name: 'frontend' }],
    folderId: 'f3',
    objects: [
      { id: '1a', type: 'text',     content: 'Flexbox — одномерная модель раскладки. display: flex превращает элемент в flex-контейнер. flex-direction задаёт направление главной оси (row / column). justify-content управляет главной осью, align-items — поперечной. flex: 1 1 0 = grow shrink basis.', createdAt: '2026-03-01T09:00:00Z' },
      { id: '1b', type: 'document', content: 'mdn-css-flexbox.pdf', cover: 'https://image.thum.io/get/width/600/crop/800/https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_flexible_box_layout/Basic_concepts_of_flexbox', createdAt: '2026-03-01T09:01:00Z' },
      { id: '1c', type: 'link',     content: 'https://developer.mozilla.org/ru/docs/Web/CSS/CSS_flexible_box_layout/Basic_concepts_of_flexbox', createdAt: '2026-03-01T09:02:00Z' },
    ],
    createdAt: '2026-03-01T09:00:00Z',
    updatedAt: '2026-03-01T09:02:00Z',
  },

  // 2 · CSS Grid — composite
  {
    id: '2',
    slug: 'mdn-css-grid',
    type: 'composite',
    title: 'CSS Grid Layout — MDN',
    cover: null,
    tags: [{ id: '2-mdn', name: 'mdn' }, { id: '2-css', name: 'css' }, { id: '2-fe', name: 'frontend' }],
    folderId: 'f3',
    objects: [
      { id: '2a', type: 'text',     content: 'CSS Grid — двумерная система. grid-template-columns: repeat(3, 1fr) создаёт три равные колонки. fr — доля свободного места. minmax(200px, 1fr) ограничивает трек. grid-area даёт имена зонам. auto-fill vs auto-fit: auto-fit схлопывает пустые треки.', createdAt: '2026-03-02T09:00:00Z' },
      { id: '2b', type: 'document', content: 'mdn-css-grid.pdf', cover: 'https://image.thum.io/get/width/600/crop/800/https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_grid_layout', createdAt: '2026-03-02T09:01:00Z' },
      { id: '2c', type: 'link',     content: 'https://developer.mozilla.org/ru/docs/Web/CSS/CSS_grid_layout', createdAt: '2026-03-02T09:02:00Z' },
    ],
    createdAt: '2026-03-02T09:00:00Z',
    updatedAt: '2026-03-02T09:02:00Z',
  },

  // 3 · Array methods — collection
  {
    id: '3',
    slug: 'mdn-array-methods',
    type: 'collection',
    title: 'Array Methods — MDN',
    cover: null,
    tags: [{ id: '3-mdn', name: 'mdn' }, { id: '3-js', name: 'js' }],
    folderId: 'f4',
    objects: [
      { id: '3a', type: 'text',  content: 'Иммутабельные методы (ES2023): toSorted(), toReversed(), toSpliced(), with(). Не мутируют оригинал — возвращают новый массив. Array.from() принимает iterable и map-функцию.', createdAt: '2026-03-03T09:00:00Z' },
      { id: '3b', type: 'link',  content: 'https://developer.mozilla.org/ru/docs/Web/JavaScript/Reference/Global_Objects/Array/reduce', createdAt: '2026-03-03T09:01:00Z' },
      { id: '3c', type: 'link',  content: 'https://developer.mozilla.org/ru/docs/Web/JavaScript/Reference/Global_Objects/Array/flatMap', createdAt: '2026-03-03T09:02:00Z' },
      { id: '3d', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/toSorted', createdAt: '2026-03-03T09:03:00Z' },
      { id: '3e', type: 'image', content: 'https://images.unsplash.com/photo-1461749280684-dccba630e2f6?w=400&h=300&fit=crop', createdAt: '2026-03-03T09:04:00Z' },
    ],
    createdAt: '2026-03-03T09:00:00Z',
    updatedAt: '2026-03-03T09:04:00Z',
  },

  // 4 · Promise — composite
  {
    id: '4',
    slug: 'mdn-promise',
    type: 'composite',
    title: 'Promise API — MDN',
    cover: null,
    tags: [{ id: '4-mdn', name: 'mdn' }, { id: '4-js', name: 'js' }],
    folderId: 'f4',
    objects: [
      { id: '4a', type: 'text',     content: 'Promise.all([]) — ждёт все, падает при первой ошибке. Promise.allSettled([]) — всегда ждёт все, возвращает [{status, value/reason}]. Promise.any([]) — первый успешный. Promise.race([]) — первый завершённый. Возвращают Promise, цепочки через .then().catch().finally().', createdAt: '2026-03-04T09:00:00Z' },
      { id: '4b', type: 'document', content: 'mdn-promise.pdf', cover: 'https://image.thum.io/get/width/600/crop/800/https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise', createdAt: '2026-03-04T09:01:00Z' },
      { id: '4c', type: 'link',     content: 'https://developer.mozilla.org/ru/docs/Web/JavaScript/Reference/Global_Objects/Promise', createdAt: '2026-03-04T09:02:00Z' },
    ],
    createdAt: '2026-03-04T09:00:00Z',
    updatedAt: '2026-03-04T09:02:00Z',
  },

  // 5 · Fetch API — composite
  {
    id: '5',
    slug: 'mdn-fetch-api',
    type: 'composite',
    title: 'Fetch API — MDN',
    cover: null,
    tags: [{ id: '5-mdn', name: 'mdn' }, { id: '5-js', name: 'js' }, { id: '5-api', name: 'web-api' }],
    folderId: 'f4',
    objects: [
      { id: '5a', type: 'text',     content: 'fetch() возвращает Promise<Response>. Response.ok — статус 200-299. response.json() / .text() / .blob() — тоже Promise. Для отмены — AbortController + signal. Credentials: "include" отправляет cookies cross-origin. Cache: "no-store" отключает кэш.', createdAt: '2026-03-05T09:00:00Z' },
      { id: '5b', type: 'document', content: 'mdn-fetch-api.pdf', cover: 'https://image.thum.io/get/width/600/crop/800/https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch', createdAt: '2026-03-05T09:01:00Z' },
      { id: '5c', type: 'link',     content: 'https://developer.mozilla.org/ru/docs/Web/API/Fetch_API/Using_Fetch', createdAt: '2026-03-05T09:02:00Z' },
      { id: '5d', type: 'image',    content: 'https://images.unsplash.com/photo-1498050108023-c5249f4df085?w=400&h=300&fit=crop', createdAt: '2026-03-05T09:03:00Z' },
    ],
    createdAt: '2026-03-05T09:00:00Z',
    updatedAt: '2026-03-05T09:03:00Z',
  },

  // 6 · CSS Custom Properties — simple
  {
    id: '6',
    slug: 'mdn-css-custom-properties',
    type: 'simple',
    title: 'CSS Custom Properties — MDN',
    cover: null,
    tags: [{ id: '6-mdn', name: 'mdn' }, { id: '6-css', name: 'css' }],
    folderId: 'f3',
    objects: [
      { id: '6a', type: 'text', content: 'Определяются на :root { --color-primary: #0070f3; }. Используются: color: var(--color-primary, fallback). Наследуются по дереву, можно переопределить на любом элементе. @property позволяет задать тип, начальное значение и анимируемость. Недоступны в медиазапросах, но работают внутри @keyframes.', createdAt: '2026-03-06T09:00:00Z' },
    ],
    createdAt: '2026-03-06T09:00:00Z',
    updatedAt: '2026-03-06T09:00:00Z',
  },

  // 7 · Web Workers — composite
  {
    id: '7',
    slug: 'mdn-web-workers',
    type: 'composite',
    title: 'Web Workers API — MDN',
    cover: null,
    tags: [{ id: '7-mdn', name: 'mdn' }, { id: '7-js', name: 'js' }, { id: '7-api', name: 'web-api' }],
    folderId: 'f4',
    objects: [
      { id: '7a', type: 'text',     content: 'Worker выполняется в отдельном потоке без доступа к DOM. Общение через postMessage() / onmessage. SharedWorker — общий для вкладок одного origin. Transferable objects (ArrayBuffer) передаются без копирования. OffscreenCanvas — рисование в воркере.', createdAt: '2026-03-07T09:00:00Z' },
      { id: '7b', type: 'document', content: 'mdn-web-workers.pdf', cover: 'https://image.thum.io/get/width/600/crop/800/https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API', createdAt: '2026-03-07T09:01:00Z' },
      { id: '7c', type: 'link',     content: 'https://developer.mozilla.org/ru/docs/Web/API/Web_Workers_API', createdAt: '2026-03-07T09:02:00Z' },
    ],
    createdAt: '2026-03-07T09:00:00Z',
    updatedAt: '2026-03-07T09:02:00Z',
  },

  // 8 · Service Worker — composite
  {
    id: '8',
    slug: 'mdn-service-worker',
    type: 'composite',
    title: 'Service Worker API — MDN',
    cover: null,
    tags: [{ id: '8-mdn', name: 'mdn' }, { id: '8-js', name: 'js' }, { id: '8-api', name: 'web-api' }],
    folderId: 'f4',
    objects: [
      { id: '8a', type: 'text',     content: 'Service Worker — прокси между браузером и сетью. Жизненный цикл: install → activate → fetch. Кэш стратегии: Cache First, Network First, Stale-While-Revalidate. Работает только на HTTPS (или localhost). navigator.serviceWorker.register("/sw.js").', createdAt: '2026-03-08T09:00:00Z' },
      { id: '8b', type: 'document', content: 'mdn-service-worker.pdf', cover: 'https://image.thum.io/get/width/600/crop/800/https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API', createdAt: '2026-03-08T09:01:00Z' },
      { id: '8c', type: 'link',     content: 'https://developer.mozilla.org/ru/docs/Web/API/Service_Worker_API', createdAt: '2026-03-08T09:02:00Z' },
      { id: '8d', type: 'link',     content: 'https://developer.mozilla.org/en-US/docs/Web/API/Cache', createdAt: '2026-03-08T09:03:00Z' },
    ],
    createdAt: '2026-03-08T09:00:00Z',
    updatedAt: '2026-03-08T09:03:00Z',
  },

  // 9 · CSS Animations — collection
  {
    id: '9',
    slug: 'mdn-css-animations',
    type: 'collection',
    title: 'CSS Animations — MDN',
    cover: null,
    tags: [{ id: '9-mdn', name: 'mdn' }, { id: '9-css', name: 'css' }, { id: '9-anim', name: 'animation' }],
    folderId: 'f3',
    objects: [
      { id: '9a', type: 'text',  content: '@keyframes задаёт ключевые кадры. animation: name duration timing-function delay iteration-count direction fill-mode. will-change: transform — GPU-слой. prefers-reduced-motion — уважай пользователя.', createdAt: '2026-03-09T09:00:00Z' },
      { id: '9b', type: 'link',  content: 'https://developer.mozilla.org/ru/docs/Web/CSS/CSS_animations/Using_CSS_animations', createdAt: '2026-03-09T09:01:00Z' },
      { id: '9c', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/CSS/transition', createdAt: '2026-03-09T09:02:00Z' },
      { id: '9d', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/CSS/animation-timeline', createdAt: '2026-03-09T09:03:00Z' },
      { id: '9e', type: 'image', content: 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400&h=300&fit=crop', createdAt: '2026-03-09T09:04:00Z' },
    ],
    createdAt: '2026-03-09T09:00:00Z',
    updatedAt: '2026-03-09T09:04:00Z',
  },

  // 10 · JavaScript Generators — simple
  {
    id: '10',
    slug: 'mdn-generators',
    type: 'simple',
    title: 'Generators & Iterators — MDN',
    cover: null,
    tags: [{ id: '10-mdn', name: 'mdn' }, { id: '10-js', name: 'js' }],
    folderId: 'f4',
    objects: [
      { id: '10a', type: 'text', content: 'function* — генераторная функция. yield приостанавливает выполнение и возвращает значение. next() возобновляет. Можно передать значение в next(val) — оно становится результатом yield. for...of автоматически вызывает iterator. yield* делегирует другому итерируемому. Применение: бесконечные последовательности, ленивые вычисления, co-routines.', createdAt: '2026-03-10T09:00:00Z' },
    ],
    createdAt: '2026-03-10T09:00:00Z',
    updatedAt: '2026-03-10T09:00:00Z',
  },

  // 11 · ResizeObserver — simple
  {
    id: '11',
    slug: 'mdn-resize-observer',
    type: 'simple',
    title: 'ResizeObserver — MDN',
    cover: null,
    tags: [{ id: '11-mdn', name: 'mdn' }, { id: '11-js', name: 'js' }, { id: '11-api', name: 'web-api' }],
    folderId: 'f4',
    objects: [
      { id: '11a', type: 'text', content: 'ResizeObserver наблюдает за изменением размеров элемента. Callback получает ResizeObserverEntry[]: entry.contentRect, entry.borderBoxSize, entry.devicePixelContentBoxSize. Точнее window.resize для отслеживания конкретных элементов. Не вызывает layout thrashing при правильном использовании.', createdAt: '2026-03-11T09:00:00Z' },
    ],
    createdAt: '2026-03-11T09:00:00Z',
    updatedAt: '2026-03-11T09:00:00Z',
  },

  // 12 · Intersection Observer — composite
  {
    id: '12',
    slug: 'mdn-intersection-observer',
    type: 'composite',
    title: 'Intersection Observer — MDN',
    cover: null,
    tags: [{ id: '12-mdn', name: 'mdn' }, { id: '12-js', name: 'js' }, { id: '12-api', name: 'web-api' }],
    folderId: 'f4',
    objects: [
      { id: '12a', type: 'text',  content: 'Отслеживает пересечение элемента с viewport или другим элементом. options: { root, rootMargin, threshold }. threshold: [0, 0.5, 1.0] — порог срабатывания. entry.isIntersecting — видим ли элемент. Применение: lazy-load изображений, infinite scroll, анимации при скролле, аналитика.', createdAt: '2026-03-12T09:00:00Z' },
      { id: '12b', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/API/Intersection_Observer_API', createdAt: '2026-03-12T09:01:00Z' },
      { id: '12c', type: 'image', content: 'https://images.unsplash.com/photo-1542831371-29b0f74f9713?w=400&h=300&fit=crop', createdAt: '2026-03-12T09:02:00Z' },
    ],
    createdAt: '2026-03-12T09:00:00Z',
    updatedAt: '2026-03-12T09:02:00Z',
  },

  // 13 · CSS :has() — simple
  {
    id: '13',
    slug: 'mdn-css-has',
    type: 'simple',
    title: 'CSS :has() Selector — MDN',
    cover: null,
    tags: [{ id: '13-mdn', name: 'mdn' }, { id: '13-css', name: 'css' }],
    folderId: 'f3',
    objects: [
      { id: '13a', type: 'text', content: ':has() — "родительский" селектор. form:has(input:invalid) — форма содержащая невалидный инпут. Поддержка всеми браузерами с 2023. Нельзя вложить :has() внутрь :has(). Работает и не с предками: li:has(+ li) — каждый li перед которым есть другой li.', createdAt: '2026-03-13T09:00:00Z' },
    ],
    createdAt: '2026-03-13T09:00:00Z',
    updatedAt: '2026-03-13T09:00:00Z',
  },

  // 14 · Container Queries — composite
  {
    id: '14',
    slug: 'mdn-container-queries',
    type: 'composite',
    title: 'CSS Container Queries — MDN',
    cover: null,
    tags: [{ id: '14-mdn', name: 'mdn' }, { id: '14-css', name: 'css' }, { id: '14-fe', name: 'frontend' }],
    folderId: 'f3',
    objects: [
      { id: '14a', type: 'text',     content: 'container-type: inline-size объявляет контейнер. @container (min-width: 400px) { } — как медиазапрос, но для компонента. container-name именует контейнер для вложенных @container. cqi / cqb — единицы размера контейнера. Можно избавиться от многих layout-зависимых медиазапросов.', createdAt: '2026-03-14T09:00:00Z' },
      { id: '14b', type: 'document', content: 'mdn-container-queries.pdf', cover: 'https://image.thum.io/get/width/600/crop/800/https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_containment/Container_queries', createdAt: '2026-03-14T09:01:00Z' },
      { id: '14c', type: 'link',     content: 'https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_containment/Container_queries', createdAt: '2026-03-14T09:02:00Z' },
    ],
    createdAt: '2026-03-14T09:00:00Z',
    updatedAt: '2026-03-14T09:02:00Z',
  },

  // 15 · async/await — simple
  {
    id: '15',
    slug: 'mdn-async-await',
    type: 'simple',
    title: 'async / await — MDN',
    cover: null,
    tags: [{ id: '15-mdn', name: 'mdn' }, { id: '15-js', name: 'js' }],
    folderId: 'f4',
    objects: [
      { id: '15a', type: 'text', content: 'async function всегда возвращает Promise. await приостанавливает только текущую async-функцию, не блокирует поток. try/catch перехватывает rejected Promise. await Promise.all([a(), b()]) — параллельно. Ошибка: await внутри forEach не работает как ожидается — использовать for...of.', createdAt: '2026-03-15T09:00:00Z' },
    ],
    createdAt: '2026-03-15T09:00:00Z',
    updatedAt: '2026-03-15T09:00:00Z',
  },

  // 16 · Web Components — collection
  {
    id: '16',
    slug: 'mdn-web-components',
    type: 'collection',
    title: 'Web Components — MDN',
    cover: null,
    tags: [{ id: '16-mdn', name: 'mdn' }, { id: '16-js', name: 'js' }, { id: '16-html', name: 'html' }, { id: '16-api', name: 'web-api' }],
    folderId: 'f4',
    objects: [
      { id: '16a', type: 'text',  content: 'Три технологии: Custom Elements, Shadow DOM, HTML Templates. customElements.define("my-el", MyEl). Shadow DOM изолирует стили. <template> + <slot>. connectedCallback / disconnectedCallback / attributeChangedCallback — жизненный цикл.', createdAt: '2026-03-16T09:00:00Z' },
      { id: '16b', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/API/Web_components', createdAt: '2026-03-16T09:01:00Z' },
      { id: '16c', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/API/ShadowRoot', createdAt: '2026-03-16T09:02:00Z' },
      { id: '16d', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/HTML/Element/template', createdAt: '2026-03-16T09:03:00Z' },
      { id: '16e', type: 'image', content: 'https://images.unsplash.com/photo-1516116216624-53e697fedbea?w=400&h=300&fit=crop', createdAt: '2026-03-16T09:04:00Z' },
    ],
    createdAt: '2026-03-16T09:00:00Z',
    updatedAt: '2026-03-16T09:04:00Z',
  },

  // 17 · CSS scroll-snap — simple
  {
    id: '17',
    slug: 'mdn-scroll-snap',
    type: 'simple',
    title: 'CSS Scroll Snap — MDN',
    cover: null,
    tags: [{ id: '17-mdn', name: 'mdn' }, { id: '17-css', name: 'css' }],
    folderId: 'f3',
    objects: [
      { id: '17a', type: 'text', content: 'На контейнере: scroll-snap-type: x mandatory | y proximity. На детях: scroll-snap-align: start | center | end. scroll-snap-stop: always запрещает пропуск снапа. scroll-padding-top компенсирует sticky-шапку. Работает нативно без JS — производительно.', createdAt: '2026-03-17T09:00:00Z' },
    ],
    createdAt: '2026-03-17T09:00:00Z',
    updatedAt: '2026-03-17T09:00:00Z',
  },

  // 18 · JavaScript Proxy — simple
  {
    id: '18',
    slug: 'mdn-proxy-reflect',
    type: 'simple',
    title: 'Proxy & Reflect — MDN',
    cover: null,
    tags: [{ id: '18-mdn', name: 'mdn' }, { id: '18-js', name: 'js' }],
    folderId: 'f4',
    objects: [
      { id: '18a', type: 'text', content: 'new Proxy(target, handler) перехватывает операции над объектом. Ловушки: get, set, has, deleteProperty, apply, construct. Reflect предоставляет дефолтное поведение для каждой ловушки. Vue 3 reactivity построена на Proxy. Отличие от Object.defineProperty: работает с массивами и динамическими свойствами.', createdAt: '2026-03-18T09:00:00Z' },
    ],
    createdAt: '2026-03-18T09:00:00Z',
    updatedAt: '2026-03-18T09:00:00Z',
  },

  // 19 · CSS clamp() — simple
  {
    id: '19',
    slug: 'mdn-css-clamp',
    type: 'simple',
    title: 'CSS clamp() & fluid type — MDN',
    cover: null,
    tags: [{ id: '19-mdn', name: 'mdn' }, { id: '19-css', name: 'css' }, { id: '19-fe', name: 'frontend' }],
    folderId: 'f3',
    objects: [
      { id: '19a', type: 'text', content: 'clamp(MIN, VAL, MAX) — значение зажато между минимумом и максимумом. font-size: clamp(1rem, 2.5vw, 2rem) — fluid типографика без медиазапросов. Также: min(), max(). Сочетание: clamp(1rem, 1rem + 1vw, 1.5rem) — относительный рост.', createdAt: '2026-03-19T09:00:00Z' },
    ],
    createdAt: '2026-03-19T09:00:00Z',
    updatedAt: '2026-03-19T09:00:00Z',
  },

  // 20 · MutationObserver — composite
  {
    id: '20',
    slug: 'mdn-mutation-observer',
    type: 'composite',
    title: 'MutationObserver — MDN',
    cover: null,
    tags: [{ id: '20-mdn', name: 'mdn' }, { id: '20-js', name: 'js' }, { id: '20-api', name: 'web-api' }],
    folderId: 'f4',
    objects: [
      { id: '20a', type: 'text',  content: 'Наблюдает за изменениями DOM. observe(node, { childList, subtree, attributes, characterData }). Callback: (MutationRecord[], observer) => void. MutationRecord.type: "childList" | "attributes" | "characterData". Отключить: observer.disconnect(). Заменяет мутировавшие DOMNodeInserted-события.', createdAt: '2026-03-20T09:00:00Z' },
      { id: '20b', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver', createdAt: '2026-03-20T09:01:00Z' },
      { id: '20c', type: 'image', content: 'https://images.unsplash.com/photo-1461749280684-dccba630e2f6?w=400&h=300&fit=crop', createdAt: '2026-03-20T09:02:00Z' },
    ],
    createdAt: '2026-03-20T09:00:00Z',
    updatedAt: '2026-03-20T09:02:00Z',
  },

  // 21 · CSS :is() :where() :not() — simple
  {
    id: '21',
    slug: 'mdn-css-is-where-not',
    type: 'simple',
    title: 'CSS :is() :where() :not() — MDN',
    cover: null,
    tags: [{ id: '21-mdn', name: 'mdn' }, { id: '21-css', name: 'css' }],
    folderId: 'f3',
    objects: [
      { id: '21a', type: 'text', content: ':is(h1, h2, h3) { } группирует селекторы, специфичность = максимальному аргументу. :where() то же, но специфичность 0 — удобно для сброса стилей. :not(p) — не p. :not() принимает список с 2021. :is() и :where() прощают невалидные селекторы в списке.', createdAt: '2026-03-21T09:00:00Z' },
    ],
    createdAt: '2026-03-21T09:00:00Z',
    updatedAt: '2026-03-21T09:00:00Z',
  },

  // 22 · ES Modules — composite
  {
    id: '22',
    slug: 'mdn-es-modules',
    type: 'composite',
    title: 'ES Modules — MDN',
    cover: null,
    tags: [{ id: '22-mdn', name: 'mdn' }, { id: '22-js', name: 'js' }],
    folderId: 'f4',
    objects: [
      { id: '22a', type: 'text',     content: 'import / export статический анализ — tree-shaking. import() динамический — code-splitting. import.meta.url — URL текущего модуля. Модули строгий режим по умолчанию, this на верхнем уровне = undefined. <script type="module"> автоматически defer. Циклические зависимости разрешаются, но осторожно.', createdAt: '2026-03-22T09:00:00Z' },
      { id: '22b', type: 'document', content: 'mdn-es-modules.pdf', cover: 'https://image.thum.io/get/width/600/crop/800/https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules', createdAt: '2026-03-22T09:01:00Z' },
      { id: '22c', type: 'link',     content: 'https://developer.mozilla.org/ru/docs/Web/JavaScript/Guide/Modules', createdAt: '2026-03-22T09:02:00Z' },
    ],
    createdAt: '2026-03-22T09:00:00Z',
    updatedAt: '2026-03-22T09:02:00Z',
  },

  // 23 · CSS Subgrid — composite
  {
    id: '23',
    slug: 'mdn-css-subgrid',
    type: 'composite',
    title: 'CSS Subgrid — MDN',
    cover: null,
    tags: [{ id: '23-mdn', name: 'mdn' }, { id: '23-css', name: 'css' }, { id: '23-fe', name: 'frontend' }],
    folderId: 'f3',
    objects: [
      { id: '23a', type: 'text',     content: 'Вложенный элемент может унаследовать треки родительской сетки: grid-template-columns: subgrid. Решает проблему выравнивания элементов в карточках разной высоты. Поддержка во всех браузерах с 2023. Можно применять только к столбцам, оставив строки независимыми.', createdAt: '2026-03-23T09:00:00Z' },
      { id: '23b', type: 'document', content: 'mdn-css-subgrid.pdf', cover: 'https://image.thum.io/get/width/600/crop/800/https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_grid_layout/Subgrid', createdAt: '2026-03-23T09:01:00Z' },
      { id: '23c', type: 'link',     content: 'https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_grid_layout/Subgrid', createdAt: '2026-03-23T09:02:00Z' },
    ],
    createdAt: '2026-03-23T09:00:00Z',
    updatedAt: '2026-03-23T09:02:00Z',
  },

  // 24 · View Transitions API — composite
  {
    id: '24',
    slug: 'mdn-view-transitions',
    type: 'composite',
    title: 'View Transitions API — MDN',
    cover: null,
    tags: [{ id: '24-mdn', name: 'mdn' }, { id: '24-js', name: 'js' }, { id: '24-api', name: 'web-api' }, { id: '24-anim', name: 'animation' }],
    folderId: 'f4',
    objects: [
      { id: '24a', type: 'text',     content: 'document.startViewTransition(() => updateDOM()) анимирует переходы. Браузер делает скриншот до/после, анимирует по умолчанию (crossfade). view-transition-name именует элемент для shared-element transition. CSS: ::view-transition-old(name) / ::view-transition-new(name). MPA поддержка через @view-transition { navigation: auto }.', createdAt: '2026-03-24T09:00:00Z' },
      { id: '24b', type: 'document', content: 'mdn-view-transitions.pdf', cover: 'https://image.thum.io/get/width/600/crop/800/https://developer.mozilla.org/en-US/docs/Web/API/View_Transitions_API', createdAt: '2026-03-24T09:01:00Z' },
      { id: '24c', type: 'link',     content: 'https://developer.mozilla.org/en-US/docs/Web/API/View_Transitions_API', createdAt: '2026-03-24T09:02:00Z' },
      { id: '24d', type: 'image',    content: 'https://images.unsplash.com/photo-1587620962725-abab7fe55159?w=400&h=300&fit=crop', createdAt: '2026-03-24T09:03:00Z' },
    ],
    createdAt: '2026-03-24T09:00:00Z',
    updatedAt: '2026-03-24T09:03:00Z',
  },

  // 25 · CSS Cascade Layers — composite
  {
    id: '25',
    slug: 'mdn-cascade-layers',
    type: 'composite',
    title: 'CSS Cascade Layers — MDN',
    cover: null,
    tags: [{ id: '25-mdn', name: 'mdn' }, { id: '25-css', name: 'css' }, { id: '25-fe', name: 'frontend' }],
    folderId: 'f3',
    objects: [
      { id: '25a', type: 'text',     content: '@layer base, components, utilities объявляет порядок слоёв. Стили в более позднем слое перекрывают ранний независимо от специфичности. @layer utilities { .mt-4 { margin-top: 1rem; } } — утилитарные стили без !important. Unlayered стили имеют наивысший приоритет среди авторских.', createdAt: '2026-03-25T09:00:00Z' },
      { id: '25b', type: 'document', content: 'mdn-cascade-layers.pdf', cover: 'https://image.thum.io/get/width/600/crop/800/https://developer.mozilla.org/en-US/docs/Web/CSS/@layer', createdAt: '2026-03-25T09:01:00Z' },
      { id: '25c', type: 'link',     content: 'https://developer.mozilla.org/en-US/docs/Web/CSS/@layer', createdAt: '2026-03-25T09:02:00Z' },
    ],
    createdAt: '2026-03-25T09:00:00Z',
    updatedAt: '2026-03-25T09:02:00Z',
  },

  // 26 · AbortController — simple
  {
    id: '26',
    slug: 'mdn-abort-controller',
    type: 'simple',
    title: 'AbortController — MDN',
    cover: null,
    tags: [{ id: '26-mdn', name: 'mdn' }, { id: '26-js', name: 'js' }, { id: '26-api', name: 'web-api' }],
    folderId: 'f4',
    objects: [
      { id: '26a', type: 'text', content: 'const controller = new AbortController(). fetch(url, { signal: controller.signal }). controller.abort() отменяет запрос — Promise rejected с AbortError. В React useEffect: return () => controller.abort(). Также работает с addEventListener, имеет третий аргумент { signal }.', createdAt: '2026-03-26T09:00:00Z' },
    ],
    createdAt: '2026-03-26T09:00:00Z',
    updatedAt: '2026-03-26T09:00:00Z',
  },

  // 27 · CSS Logical Properties — simple
  {
    id: '27',
    slug: 'mdn-css-logical-properties',
    type: 'simple',
    title: 'CSS Logical Properties — MDN',
    cover: null,
    tags: [{ id: '27-mdn', name: 'mdn' }, { id: '27-css', name: 'css' }],
    folderId: 'f3',
    objects: [
      { id: '27a', type: 'text', content: 'Logical properties адаптируются к writing-mode и direction. margin-inline-start вместо margin-left. padding-block = padding-top + padding-bottom. inset-inline-start вместо left. border-block-end вместо border-bottom. Важно для RTL и вертикального текста.', createdAt: '2026-03-27T09:00:00Z' },
    ],
    createdAt: '2026-03-27T09:00:00Z',
    updatedAt: '2026-03-27T09:00:00Z',
  },

  // 28 · IndexedDB — composite
  {
    id: '28',
    slug: 'mdn-indexeddb',
    type: 'composite',
    title: 'IndexedDB API — MDN',
    cover: null,
    tags: [{ id: '28-mdn', name: 'mdn' }, { id: '28-js', name: 'js' }, { id: '28-api', name: 'web-api' }],
    folderId: 'f4',
    objects: [
      { id: '28a', type: 'text',  content: 'Транзакционная NoSQL БД в браузере. Хранит любые JS-объекты. Работает асинхронно. Основа для многих offline-решений. Интерфейс довольно низкоуровневый — обычно используют idb-keyval или Dexie.js поверх.', createdAt: '2026-03-28T09:00:00Z' },
      { id: '28b', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API', createdAt: '2026-03-28T09:01:00Z' },
      { id: '28c', type: 'image', content: 'https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=400&h=300&fit=crop', createdAt: '2026-03-28T09:02:00Z' },
    ],
    createdAt: '2026-03-28T09:00:00Z',
    updatedAt: '2026-03-28T09:02:00Z',
  },

  // 29 · CSS Grid dense / auto-placement — collection
  {
    id: '29',
    slug: 'mdn-grid-auto-placement',
    type: 'collection',
    title: 'Grid Auto Placement — MDN',
    cover: null,
    tags: [{ id: '29-mdn', name: 'mdn' }, { id: '29-css', name: 'css' }, { id: '29-fe', name: 'frontend' }],
    folderId: 'f3',
    objects: [
      { id: '29a', type: 'text',  content: 'grid-auto-flow: dense заполняет дыры меньшими элементами. grid-column: span 2 растягивает на 2 колонки. grid-auto-rows: minmax(100px, auto) — высота строк. Явная и неявная сетка.', createdAt: '2026-03-29T09:00:00Z' },
      { id: '29b', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_grid_layout/Auto-placement_in_grid_layout', createdAt: '2026-03-29T09:01:00Z' },
      { id: '29c', type: 'link',  content: 'https://developer.mozilla.org/en-US/docs/Web/CSS/grid-auto-flow', createdAt: '2026-03-29T09:02:00Z' },
      { id: '29d', type: 'image', content: 'https://images.unsplash.com/photo-1517694712202-14dd9538aa97?w=400&h=300&fit=crop', createdAt: '2026-03-29T09:03:00Z' },
    ],
    createdAt: '2026-03-29T09:00:00Z',
    updatedAt: '2026-03-29T09:03:00Z',
  },

  // 30 · WeakMap & WeakSet — simple
  {
    id: '30',
    slug: 'mdn-weakmap-weakset',
    type: 'simple',
    title: 'WeakMap & WeakSet — MDN',
    cover: null,
    tags: [{ id: '30-mdn', name: 'mdn' }, { id: '30-js', name: 'js' }],
    folderId: 'f4',
    objects: [
      { id: '30a', type: 'text', content: 'WeakMap/WeakSet держат слабые ссылки на объекты — не мешают GC. WeakMap ключи — только объекты. Не итерируемы, нет size. Применение: хранить метаданные к объектам без утечек памяти. WeakRef и FinalizationRegistry — более низкоуровневый контроль.', createdAt: '2026-03-30T09:00:00Z' },
    ],
    createdAt: '2026-03-30T09:00:00Z',
    updatedAt: '2026-03-30T09:00:00Z',
  },

  // ─── Остальные заметки ────────────────────────────────────────────────────

  {
    id: '31',
    slug: 'react-performance-tips',
    type: 'simple',
    title: 'React Performance Tips',
    cover: null,
    tags: [{ id: '31-react', name: 'react' }, { id: '31-perf', name: 'performance' }],
    folderId: 'f1',
    objects: [
      { id: 'o31', type: 'text', content: 'React.memo мемоизирует компонент. useMemo/useCallback — вычисления и функции. React Compiler (RC) автоматизирует большинство случаев. key при рендере списков обязателен. Профилировать через React DevTools Profiler.', createdAt: '2026-04-01T10:00:00Z' },
    ],
    createdAt: '2026-04-01T10:00:00Z',
    updatedAt: '2026-04-01T10:00:00Z',
  },

  {
    id: '32',
    slug: 'design-resources',
    type: 'collection',
    title: 'Design Resources',
    cover: null,
    tags: [{ id: '32-design', name: 'design' }, { id: '32-links', name: 'links' }],
    folderId: 'f2',
    objects: [
      { id: 'o32a', type: 'image', content: 'https://images.unsplash.com/photo-1561070791-2526d30994b5?w=400&h=300&fit=crop', createdAt: '2026-04-02T10:00:00Z' },
      { id: 'o32b', type: 'image', content: 'https://images.unsplash.com/photo-1626785774625-0b1c2c4eab67?w=400&h=300&fit=crop', createdAt: '2026-04-02T10:01:00Z' },
      { id: 'o32c', type: 'image', content: 'https://images.unsplash.com/photo-1545235617-9465d2a55698?w=400&h=300&fit=crop', createdAt: '2026-04-02T10:02:00Z' },
      { id: 'o32d', type: 'link',  content: 'https://figma.com',    createdAt: '2026-04-02T10:05:00Z' },
      { id: 'o32e', type: 'link',  content: 'https://dribbble.com', createdAt: '2026-04-02T10:06:00Z' },
    ],
    createdAt: '2026-04-02T10:00:00Z',
    updatedAt: '2026-04-02T10:06:00Z',
  },

  {
    id: '33',
    slug: 'system-architecture',
    type: 'composite',
    title: 'System Architecture',
    cover: null,
    tags: [{ id: '33-arch', name: 'arch' }, { id: '33-backend', name: 'backend' }],
    folderId: 'f1',
    objects: [
      { id: 'o33a', type: 'text',     content: 'Микросервисы, очереди событий, API gateway. Каждый сервис — одна зона ответственности. Event sourcing + CQRS для write-heavy систем.', createdAt: '2026-04-03T10:00:00Z' },
      { id: 'o33b', type: 'document', content: 'architecture.pdf', cover: 'https://images.unsplash.com/photo-1618044733300-9472054094ee?w=600&h=800&fit=crop', createdAt: '2026-04-03T10:01:00Z' },
    ],
    createdAt: '2026-04-03T10:00:00Z',
    updatedAt: '2026-04-03T10:01:00Z',
  },

  {
    id: '34',
    slug: 'book-notes-2026',
    type: 'collection',
    title: 'Book Notes 2026',
    cover: null,
    tags: [{ id: '34-books', name: 'books' }, { id: '34-learn', name: 'learning' }],
    folderId: null,
    objects: [
      { id: 'o34a', type: 'image', content: 'https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=400&h=300&fit=crop', createdAt: '2026-04-05T10:00:00Z' },
      { id: 'o34b', type: 'image', content: 'https://images.unsplash.com/photo-1512820790803-83ca734da794?w=400&h=300&fit=crop', createdAt: '2026-04-05T10:01:00Z' },
      { id: 'o34c', type: 'text',  content: 'Atomic Habits', createdAt: '2026-04-05T10:06:00Z' },
      { id: 'o34d', type: 'text',  content: 'Deep Work', createdAt: '2026-04-05T10:07:00Z' },
      { id: 'o34e', type: 'text',  content: 'Designing Data-Intensive Applications', createdAt: '2026-04-05T10:08:00Z' },
      { id: 'o34f', type: 'text',  content: 'A Philosophy of Software Design', createdAt: '2026-04-05T10:09:00Z' },
    ],
    createdAt: '2026-04-05T10:00:00Z',
    updatedAt: '2026-04-05T10:09:00Z',
  },

  {
    id: '35',
    slug: 'framer-motion-research',
    type: 'composite',
    title: 'Framer Motion Research',
    cover: null,
    tags: [{ id: '35-anim', name: 'animation' }, { id: '35-react', name: 'react' }],
    folderId: 'f1',
    objects: [
      { id: 'o35a', type: 'text',  content: 'layoutId связывает элементы для shared-element transitions. AnimatePresence анимирует unmount. useMotionValue + useTransform — производные значения без ре-рендера.', createdAt: '2026-04-06T10:00:00Z' },
      { id: 'o35b', type: 'link',  content: 'https://motion.dev', createdAt: '2026-04-06T10:01:00Z' },
      { id: 'o35c', type: 'image', content: 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400&h=300&fit=crop', createdAt: '2026-04-06T10:02:00Z' },
    ],
    createdAt: '2026-04-06T10:00:00Z',
    updatedAt: '2026-04-06T10:02:00Z',
  },

  {
    id: '36',
    slug: 'typescript-patterns',
    type: 'simple',
    title: 'TypeScript Advanced Patterns',
    cover: null,
    tags: [{ id: '36-ts', name: 'typescript' }, { id: '36-fe', name: 'frontend' }],
    folderId: 'f3',
    objects: [
      { id: 'o36', type: 'text', content: 'Discriminated unions + exhaustiveness checking через never. Template literal types. Conditional types. infer извлекает тип. satisfies оператор проверяет тип без widening. const assertion: as const.', createdAt: '2026-04-07T10:00:00Z' },
    ],
    createdAt: '2026-04-07T10:00:00Z',
    updatedAt: '2026-04-07T10:00:00Z',
  },

  {
    id: '37',
    slug: 'dev-tools',
    type: 'collection',
    title: 'Dev Tools',
    cover: null,
    tags: [{ id: '37-tools', name: 'tools' }, { id: '37-prod', name: 'productivity' }],
    folderId: 'f2',
    objects: [
      { id: 'o37a', type: 'image', content: 'https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=400&h=300&fit=crop', createdAt: '2026-04-08T10:00:00Z' },
      { id: 'o37b', type: 'image', content: 'https://images.unsplash.com/photo-1629654297299-c8506221ca97?w=400&h=300&fit=crop', createdAt: '2026-04-08T10:01:00Z' },
      { id: 'o37c', type: 'link',  content: 'https://linear.app',  createdAt: '2026-04-08T10:04:00Z' },
      { id: 'o37d', type: 'link',  content: 'https://warp.dev',    createdAt: '2026-04-08T10:05:00Z' },
      { id: 'o37e', type: 'link',  content: 'https://raycast.com', createdAt: '2026-04-08T10:06:00Z' },
    ],
    createdAt: '2026-04-08T10:00:00Z',
    updatedAt: '2026-04-08T10:06:00Z',
  },

  {
    id: '38',
    slug: 'postgres-research',
    type: 'composite',
    title: 'PostgreSQL Research',
    cover: null,
    tags: [{ id: '38-db', name: 'db' }, { id: '38-backend', name: 'backend' }],
    folderId: 'f4',
    objects: [
      { id: 'o38a', type: 'text',  content: 'EXPLAIN ANALYZE покажет где запрос теряет время. Partial indexes ускоряют фильтрацию. pg_trgm + GIN-индекс для full-text search. JSONB с индексами вместо EAV.', createdAt: '2026-04-09T10:00:00Z' },
      { id: 'o38b', type: 'image', content: 'https://images.unsplash.com/photo-1544383835-bda2bc66a55d?w=400&h=300&fit=crop', createdAt: '2026-04-09T10:02:00Z' },
      { id: 'o38c', type: 'link',  content: 'https://explain.dalibo.com', createdAt: '2026-04-09T10:03:00Z' },
    ],
    createdAt: '2026-04-09T10:00:00Z',
    updatedAt: '2026-04-09T10:03:00Z',
  },

  {
    id: '39',
    slug: 'mountain-photo',
    type: 'simple',
    title: 'Горный пейзаж',
    cover: null,
    tags: [{ id: '39-photo', name: 'photo' }],
    folderId: null,
    objects: [
      { id: 'o39', type: 'image', content: 'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=600&h=600&fit=crop', createdAt: '2026-04-04T10:00:00Z' },
    ],
    createdAt: '2026-04-04T10:00:00Z',
    updatedAt: '2026-04-04T10:00:00Z',
  },

  {
    id: '40',
    slug: 'css-references',
    type: 'collection',
    title: 'CSS References',
    cover: null,
    tags: [{ id: '40-css', name: 'css' }, { id: '40-fe', name: 'frontend' }],
    folderId: 'f2',
    objects: [
      { id: 'o40a', type: 'image', content: 'https://images.unsplash.com/photo-1507721999472-8ed4421c4af2?w=400&h=300&fit=crop', createdAt: '2026-04-11T10:00:00Z' },
      { id: 'o40b', type: 'image', content: 'https://images.unsplash.com/photo-1542831371-29b0f74f9713?w=400&h=300&fit=crop', createdAt: '2026-04-11T10:01:00Z' },
      { id: 'o40c', type: 'link',  content: 'https://css-tricks.com', createdAt: '2026-04-11T10:03:00Z' },
      { id: 'o40d', type: 'link',  content: 'https://web.dev',        createdAt: '2026-04-11T10:04:00Z' },
    ],
    createdAt: '2026-04-11T10:00:00Z',
    updatedAt: '2026-04-11T10:04:00Z',
  },

  {
    id: '41',
    slug: 'vim-research',
    type: 'composite',
    title: 'Vim Research',
    cover: null,
    tags: [{ id: '41-tools', name: 'tools' }, { id: '41-editor', name: 'editor' }],
    folderId: null,
    objects: [
      { id: 'o41a', type: 'text',     content: 'ci" меняет содержимое внутри кавычек. f<char> прыгает к символу на строке. % переходит к парной скобке. :s/old/new/g замена в строке. Macros: q<reg> запись, @<reg> воспроизведение.', createdAt: '2026-04-12T10:00:00Z' },
      { id: 'o41b', type: 'document', content: 'vim-cheatsheet.pdf', cover: 'https://images.unsplash.com/photo-1629654297299-c8506221ca97?w=600&h=800&fit=crop', createdAt: '2026-04-12T10:01:00Z' },
    ],
    createdAt: '2026-04-12T10:00:00Z',
    updatedAt: '2026-04-12T10:01:00Z',
  },

  {
    id: '42',
    slug: 'japan-trip',
    type: 'collection',
    title: 'Japan Trip Photos',
    cover: null,
    tags: [{ id: '42-photo', name: 'photo' }, { id: '42-travel', name: 'travel' }],
    folderId: null,
    objects: [
      { id: 'o42a', type: 'image', content: 'https://images.unsplash.com/photo-1490806843957-31f4c9a91c65?w=400&h=300&fit=crop', createdAt: '2026-05-02T10:00:00Z' },
      { id: 'o42b', type: 'image', content: 'https://images.unsplash.com/photo-1528360983277-13d401cdc186?w=400&h=300&fit=crop', createdAt: '2026-05-02T10:01:00Z' },
      { id: 'o42c', type: 'image', content: 'https://images.unsplash.com/photo-1545569341-9eb8b30979d9?w=400&h=300&fit=crop', createdAt: '2026-05-02T10:02:00Z' },
      { id: 'o42d', type: 'image', content: 'https://images.unsplash.com/photo-1551918120-9739cb430c6d?w=400&h=300&fit=crop', createdAt: '2026-05-02T10:03:00Z' },
    ],
    createdAt: '2026-05-02T10:00:00Z',
    updatedAt: '2026-05-02T10:03:00Z',
  },
]
