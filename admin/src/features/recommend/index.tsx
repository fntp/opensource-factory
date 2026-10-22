import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
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
import { fetchRecommendations, MOCK_RECOMMENDATIONS } from './api'

export function Recommend() {
  const { data } = useQuery({
    queryKey: ['recommendations'],
    queryFn: fetchRecommendations,
  })
  const [dismissed, setDismissed] = useState<string[]>([])
  const items = (data ?? MOCK_RECOMMENDATIONS).filter(
    (item) => !dismissed.includes(item.id)
  )

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
              <Sparkles className='size-6 text-violet-500' />
              智能推荐
            </h2>
            <p className='text-sm text-muted-foreground'>
              基于你的收藏与阅读偏好，通过语义匹配为你推荐可能感兴趣的开源项目。
            </p>
          </div>
        </div>

        <div className='grid gap-4 md:grid-cols-2 xl:grid-cols-3'>
          {items.map((item) => (
            <Card key={item.id} className='flex flex-col'>
              <CardHeader>
                <div className='flex items-start justify-between gap-2'>
                  <div>
                    <CardTitle className='text-base'>
                      <a
                        href={item.url}
                        target='_blank'
                        rel='noreferrer'
                        className='hover:underline'
                      >
                        {item.owner}/{item.name}
                      </a>
                    </CardTitle>
                    <CardDescription className='mt-1'>
                      {item.description}
                    </CardDescription>
                  </div>
                  <Badge className='shrink-0'>
                    匹配度 {Math.round(item.score * 100)}%
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className='flex flex-1 flex-col justify-between gap-4'>
                <p className='text-sm text-muted-foreground'>{item.reason}</p>
                <div className='space-y-3'>
                  <div className='flex flex-wrap items-center gap-1'>
                    {item.basedOn.map((tag) => (
                      <Badge key={tag} variant='outline'>
                        {tag}
                      </Badge>
                    ))}
                    <span className='ms-auto text-xs text-muted-foreground'>
                      {item.language} · {item.stars.toLocaleString()} stars
                    </span>
                  </div>
                  <div className='flex gap-2'>
                    <Button size='sm' asChild>
                      <a href={item.url} target='_blank' rel='noreferrer'>
                        查看仓库
                      </a>
                    </Button>
                    <Button
                      size='sm'
                      variant='secondary'
                      onClick={() => toast.success('已加入收藏（演示）')}
                    >
                      加入收藏
                    </Button>
                    <Button
                      size='sm'
                      variant='ghost'
                      onClick={() =>
                        setDismissed((prev) => [...prev, item.id])
                      }
                    >
                      忽略
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
          {items.length === 0 && (
            <Card className='md:col-span-2 xl:col-span-3'>
              <CardContent className='flex h-40 items-center justify-center text-muted-foreground'>
                暂时没有新的推荐，明天再来看看吧。
              </CardContent>
            </Card>
          )}
        </div>
      </Main>
    </>
  )
}
