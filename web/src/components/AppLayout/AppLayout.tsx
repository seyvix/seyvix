import { Outlet } from 'react-router-dom'
import AsideHeader from '../AsideHeader/AsideHeader'
import { TaxonomyOnboarding } from '../TaxonomyOnboarding/TaxonomyOnboarding'
import styles from './AppLayout.module.css'

export default function AppLayout() {
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
