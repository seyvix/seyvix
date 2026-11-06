import { Outlet } from 'react-router'
import { useNotesChangeFeed } from '../../hooks/useNotesChangeFeed'
import AsideHeader from '../AsideHeader/AsideHeader'
import { TaxonomyOnboarding } from '../TaxonomyOnboarding/TaxonomyOnboarding'
import styles from './AppLayout.module.css'

export default function AppLayout() {
  useNotesChangeFeed()

  return (
    <div className={styles.root}>
      <AsideHeader />
      <main className={styles.main}>
        <Outlet />
      </main>
      <TaxonomyOnboarding />
    </div>
  )
}
