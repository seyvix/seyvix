export function loader() {
  return new Response('ok', {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'public, max-age=5, stale-while-revalidate=30',
    },
  })
}
