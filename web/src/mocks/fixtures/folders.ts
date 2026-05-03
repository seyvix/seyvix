import type { Folder } from '../../types'

export const folderFixtures: Folder[] = [
  {
    id: 'f1',
    slug: 'engineering',
    name: 'Engineering',
    path: 'engineering',
    parentId: null,
    children: [
      {
        id: 'f3',
        slug: 'engineering-frontend',
        name: 'Frontend',
        path: 'engineering/frontend',
        parentId: 'f1',
        children: [],
      },
      {
        id: 'f4',
        slug: 'engineering-backend',
        name: 'Backend',
        path: 'engineering/backend',
        parentId: 'f1',
        children: [],
      },
    ],
  },
  {
    id: 'f2',
    slug: 'design',
    name: 'Design',
    path: 'design',
    parentId: null,
    children: [],
  },
]
