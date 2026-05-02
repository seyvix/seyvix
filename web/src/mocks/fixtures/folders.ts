import type { Folder } from '../../types'

export const folderFixtures: Folder[] = [
  {
    id: 'f1',
    slug: 'engineering',
    name: 'Engineering',
    parentId: null,
    children: [
      {
        id: 'f3',
        slug: 'engineering-frontend',
        name: 'Frontend',
        parentId: 'f1',
        children: [],
      },
      {
        id: 'f4',
        slug: 'engineering-backend',
        name: 'Backend',
        parentId: 'f1',
        children: [],
      },
    ],
  },
  {
    id: 'f2',
    slug: 'design',
    name: 'Design',
    parentId: null,
    children: [],
  },
]
