import type { Folder } from '../../types'

export const folderFixtures: Folder[] = [
  {
    id: 'f1',
    slug: 'engineering',
    name: 'Engineering',
    path: 'engineering',
    directCount: 1,
    totalCount: 3,
    parentId: null,
    children: [
      {
        id: 'f3',
        slug: 'engineering-frontend',
        name: 'Frontend',
        path: 'engineering/frontend',
        directCount: 1,
        totalCount: 1,
        parentId: 'f1',
        children: [],
      },
      {
        id: 'f4',
        slug: 'engineering-backend',
        name: 'Backend',
        path: 'engineering/backend',
        directCount: 1,
        totalCount: 1,
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
    directCount: 0,
    totalCount: 0,
    parentId: null,
    children: [],
  },
]
