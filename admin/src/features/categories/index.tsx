import { useQuery } from '@tanstack/react-query'
import { FolderTree, Plus, Tags } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { fetchCategories, MOCK_CATEGORIES, MOCK_TAGS } from './api'

export function Categories() {
  const { data } = useQuery({
    queryKey: ['categories'],
    queryFn: fetchCategories,
  })
  const categories = data?.categories ?? MOCK_CATEGORIES
  const tags = data?.tags ?? MOCK_TAGS

  return (
    <>
      <Header>
        <h1 className='me-auto text-lg font-semibold'>开源项目工厂</h1>
        <Search />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      <Main>
        <div className='mb-2 flex items-center justify-between space-y-2'>
          <div>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              <FolderTree className='size-6 text-emerald-600' />
              分类与标签
            </h2>
            <p className='text-sm text-muted-foreground'>
              用分类树与标签体系组织你的开源资产，方便快速检索与推荐。
            </p>
          </div>
          <Button onClick={() => toast.success('新建分类（演示）')}>
            <Plus />
            新建分类
          </Button>
        </div>

        <div className='grid grid-cols-1 gap-4 lg:grid-cols-3'>
          <Card className='lg:col-span-2'>
            <CardHeader>
              <CardTitle>分类</CardTitle>
              <CardDescription>共 {categories.length} 个分类</CardDescription>
            </CardHeader>
            <CardContent className='space-y-4'>
              {categories.map((category) => (
                <div
                  key={category.id}
                  className='flex items-center justify-between gap-4'
                >
                  <div className='min-w-0'>
                    <div className='text-sm font-medium'>{category.name}</div>
                    <div className='truncate text-sm text-muted-foreground'>
                      {category.description}
                    </div>
                  </div>
                  <Badge variant='secondary'>{category.count}</Badge>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className='flex items-center gap-2'>
                <Tags className='size-4' />
                标签
              </CardTitle>
              <CardDescription>共 {tags.length} 个标签</CardDescription>
            </CardHeader>
            <CardContent>
              <div className='flex flex-wrap gap-2'>
                {tags.map((tag) => (
                  <Badge key={tag.name} variant='outline'>
                    {tag.name} · {tag.count}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </Main>
    </>
  )
}
