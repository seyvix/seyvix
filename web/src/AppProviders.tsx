import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { UploadToast } from './components/UploadToast/UploadToast'
import { TelegramSurface } from './components/TelegramSurface/TelegramSurface'
import { AuthProvider } from './contexts/AuthContext'
import { LocalNotesProvider } from './contexts/LocalNotesContext'
import { SettingsProvider } from './contexts/SettingsContext'
import { UploadProvider } from './contexts/UploadContext'
import { isClientError } from './lib/apiError'

const MAX_QUERY_RETRIES = 2

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5 * 60_000,
        // Freshness of note data comes from the change feed, not from refetch-on-focus.
        refetchOnWindowFocus: false,
        // 4xx are deterministic (missing, forbidden, invalid): retrying only adds requests.
        retry: (failureCount, error) => !isClientError(error) && failureCount < MAX_QUERY_RETRIES,
      },
      mutations: {
        retry: false,
      },
    },
  })
}

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(createQueryClient)

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <SettingsProvider>
          <LocalNotesProvider>
            <UploadProvider>
              <TelegramSurface />
              {children}
              <UploadToast />
            </UploadProvider>
          </LocalNotesProvider>
        </SettingsProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
