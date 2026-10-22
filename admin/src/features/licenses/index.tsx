import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  HelpCircle,
  RefreshCw,
  Scale,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import {
  fetchLicenseCatalog,
  fetchLicenseSummary,
  MOCK_LICENSE_CATALOG,
  MOCK_LICENSE_SUMMARY,
  type LicenseRisk,
} from './api'
import {
  licenseCoverage,
  licenseShare,
  riskLabel,
  riskToneClass,
} from './utils'

const RISK_ORDER: LicenseRisk[] = ['low', 'medium', 'high', 'unknown']

const RISK_ICON: Record<LicenseRisk, typeof ShieldCheck> = {
  low: ShieldCheck,
  medium: AlertTriangle,
  high: ShieldAlert,
  unknown: HelpCircle,
}

export function Licenses() {
  const catalogQuery = useQuery({
    queryKey: ['license-catalog'],
    queryFn: fetchLicenseCatalog,
  })
  const summaryQuery = useQuery({
    queryKey: ['license-summary', 'all'],
    queryFn: () => fetchLicenseSummary('all'),
  })

  const catalog = catalogQuery.data ?? MOCK_LICENSE_CATALOG
  const summary = summaryQuery.data ?? MOCK_LICENSE_SUMMARY
  const coverage = licenseCoverage(summary)

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
        <div className='mb-4 flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              <Scale className='size-6 text-primary' />
              License 合规
            </h2>
            <p className='text-sm text-muted-foreground'>
              汇总我的仓库与热榜项目的许可证识别结果，按宽松 / 著佐权 / 公共领域分级提示合规风险。
            </p>
          </div>
          <Button
            variant='outline'
            onClick={() => {
              void catalogQuery.refetch()
              void summaryQuery.refetch()
            }}
          >
            <RefreshCw
              className={
                summaryQuery.isFetching ? 'animate-spin' : undefined
              }
            />
            刷新
          </Button>
        </div>

        <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
          <StatCard
            title='识别覆盖率'
            value={`${coverage}%`}
            description={`${summary.checked} / ${summary.total} 个仓库已识别`}
            icon={ShieldCheck}
          />
          <StatCard
            title='已识别许可证'
            value={String(summary.known)}
            description='包含宽松、著佐权与公共领域'
            icon={ShieldCheck}
          />
          <StatCard
            title='未识别'
            value={String(summary.unknown)}
            description='默认保留所有权利，使用前需授权'
            icon={HelpCircle}
          />
          <StatCard
            title='高风险项目'
            value={String(summary.riskCounts.high)}
            description='GPL / AGPL 等强著佐权许可'
            icon={ShieldAlert}
          />
        </div>

        <Card className='mt-4'>
          <CardHeader>
            <CardTitle>风险分布</CardTitle>
            <CardDescription>
              共统计 {summary.total} 个仓库；风险等级按许可证类型自动映射。
            </CardDescription>
          </CardHeader>
          <CardContent className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
            {RISK_ORDER.map((risk) => {
              const Icon = RISK_ICON[risk]
              return (
                <div
                  key={risk}
                  className='flex items-center justify-between rounded-lg border p-3'
                >
                  <div className='flex items-center gap-2'>
                    <Icon className='size-4 text-muted-foreground' />
                    <span className='text-sm font-medium'>
                      {riskLabel(risk)}
                    </span>
                  </div>
                  <Badge
                    variant='outline'
                    className={riskToneClass(risk)}
                  >
                    {summary.riskCounts[risk]}
                  </Badge>
                </div>
              )
            })}
          </CardContent>
        </Card>

        <Card className='mt-4'>
          <CardHeader>
            <CardTitle>许可证分布</CardTitle>
            <CardDescription>
              按仓库数量排序；未识别项目统一归入「未知许可」。
            </CardDescription>
          </CardHeader>
          <CardContent>
            {summaryQuery.isLoading ? (
              <div className='space-y-2'>
                {Array.from({ length: 4 }).map((_, index) => (
                  <Skeleton key={index} className='h-10 w-full' />
                ))}
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>许可证</TableHead>
                    <TableHead>分类</TableHead>
                    <TableHead>风险</TableHead>
                    <TableHead className='text-end'>仓库数</TableHead>
                    <TableHead className='text-end'>占比</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {summary.licenses.map((item) => (
                    <TableRow key={item.spdxId ?? 'unknown'}>
                      <TableCell className='font-medium'>
                        {item.name}
                        {item.spdxId && (
                          <span className='ml-2 text-xs text-muted-foreground'>
                            {item.spdxId}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant='secondary'>{item.categoryLabel}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant='outline'
                          className={riskToneClass(item.riskLevel)}
                        >
                          {riskLabel(item.riskLevel)}
                        </Badge>
                      </TableCell>
                      <TableCell className='text-end'>{item.count}</TableCell>
                      <TableCell className='text-end text-muted-foreground'>
                        {licenseShare(item.count, summary.total)}%
                      </TableCell>
                    </TableRow>
                  ))}
                  {summary.licenses.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        className='h-24 text-center text-muted-foreground'
                      >
                        暂无 License 数据，先运行一次补全任务。
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card className='mt-4'>
          <CardHeader>
            <CardTitle>许可证目录与义务</CardTitle>
            <CardDescription>
              目录口径与 VPS / edge 一致；合规提示仅为工程辅助信息，不构成法律意见。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>许可证</TableHead>
                  <TableHead>分类</TableHead>
                  <TableHead>风险</TableHead>
                  <TableHead>主要义务</TableHead>
                  <TableHead>提醒</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {catalog.licenses.map((item) => (
                  <TableRow key={item.spdxId}>
                    <TableCell>
                      <div className='font-medium'>{item.name}</div>
                      <div className='text-xs text-muted-foreground'>
                        {item.spdxId}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant='secondary'>
                        {catalog.categories.find(
                          (category) => category.key === item.category
                        )?.label ?? item.category}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant='outline'
                        className={riskToneClass(item.riskLevel)}
                      >
                        {riskLabel(item.riskLevel)}
                      </Badge>
                    </TableCell>
                    <TableCell className='max-w-80 text-sm text-muted-foreground'>
                      {item.obligations.length
                        ? item.obligations.join(' · ')
                        : '无强制义务'}
                    </TableCell>
                    <TableCell className='max-w-64 text-sm text-muted-foreground'>
                      {item.warnings.length ? item.warnings.join(' · ') : '—'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </Main>
    </>
  )
}

function StatCard({
  title,
  value,
  description,
  icon: Icon,
}: {
  title: string
  value: string
  description: string
  icon: typeof ShieldCheck
}) {
  return (
    <Card>
      <CardHeader className='pb-2'>
        <CardTitle className='flex items-center justify-between text-sm font-medium'>
          {title}
          <Icon className='size-4 text-muted-foreground' />
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className='text-2xl font-bold'>{value}</div>
        <p className='text-xs text-muted-foreground'>{description}</p>
      </CardContent>
    </Card>
  )
}
