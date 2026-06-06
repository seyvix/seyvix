import {
  HydrationBoundary,
  QueryClient,
  QueryClientProvider,
  type DehydratedState,
} from '@tanstack/react-query'
import { useState } from 'react'
import { UploadToast } from './components/UploadToast/UploadToast'
import { AuthProvider } from './contexts/AuthContext'
import type { UserResponse } from './api/auth'
import { LocalNotesProvider } from './contexts/LocalNotesContext'
import { SettingsProvider } from './contexts/SettingsContext'
import { UploadProvider } from './contexts/UploadContext'

declare global {
  interface Window {
    __AUTH_BOOTSTRAP__?: {
      user?: UserResponse | null
    }
    __REACT_QUERY_STATE__?: DehydratedState
  }
}

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 1000 * 60 * 5,
        retry: 1,
      },
    },
  })
}

interface AppProvidersProps {
  children: React.ReactNode
  authInitialReady?: boolean
  authInitialUser?: UserResponse | null
  authInitialAccessToken?: string | null
  dehydratedState?: DehydratedState
  queryClient?: QueryClient
}

export function AppProviders({
  children,
  authInitialReady,
  authInitialUser,
  authInitialAccessToken,
  dehydratedState,
  queryClient: providedQueryClient,
}: AppProvidersProps) {
  const [queryClient] = useState(() => providedQueryClient ?? createQueryClient())
  const browserAuth = typeof window !== 'undefined' ? window.__AUTH_BOOTSTRAP__ : undefined
  const browserQueryState = typeof window !== 'undefined' ? window.__REACT_QUERY_STATE__ : undefined
  const initialUser = authInitialUser ?? browserAuth?.user ?? null
  const initialAccessToken = authInitialAccessToken ?? null
  const initialReady = authInitialReady ?? Boolean(initialUser)
  const hydrationState = dehydratedState ?? browserQueryState

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider
        initialIsReady={initialReady}
        initialUser={initialUser}
        initialAccessToken={initialAccessToken}
      >
        <HydrationBoundary state={hydrationState}>
          <SettingsProvider>
            <LocalNotesProvider>
              <UploadProvider>
                {children}
                <UploadToast />
              </UploadProvider>
            </LocalNotesProvider>
          </SettingsProvider>
        </HydrationBoundary>
      </AuthProvider>
    </QueryClientProvider>
  )
}
