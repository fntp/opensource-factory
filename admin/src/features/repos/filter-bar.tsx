import { ArrowDown, ArrowUp, RotateCcw, Search } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Category, Tag } from '@/features/categories/api'
import {
  countActiveFilters,
  SORT_OPTIONS,
  STAR_RANGE_OPTIONS,
  TIME_RANGE_OPTIONS,
  type RepoFilters,
} from './filters'
import { MultiSelect } from './multi-select'

interface RepoFilterBarProps {
  filters: RepoFilters
  keyword: string
  categories: Category[]
  tags: Tag[]
  languages: string[]
  onKeywordChange: (value: string) => void
  onChange: (patch: Partial<RepoFilters>) => void
  onReset: () => void
}

export function RepoFilterBar({
  filters,
  keyword,
  categories,
  tags,
  languages,
  onKeywordChange,
  onChange,
  onReset,
}: RepoFilterBarProps) {
  const activeCount = countActiveFilters(filters)

  return (
    <div className='flex flex-wrap items-center gap-2'>
      <div className='relative w-full sm:w-64'>
        <Search className='pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
        <Input
          placeholder='搜索仓库、描述、语言、分类或标签…'
          value={keyword}
          onChange={(event) => onKeywordChange(event.target.value)}
          className='h-8 ps-8'
        />
      </div>

      <Select
        value={filters.categoryId || 'all'}
        onValueChange={(value) =>
          onChange({ categoryId: value === 'all' ? '' : value })
        }
      >
        <SelectTrigger size='sm' className='w-36'>
          <SelectValue placeholder='全部分类' />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value='all'>全部分类</SelectItem>
          {categories.map((category) => (
            <SelectItem key={category.id} value={category.id}>
              {category.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <MultiSelect
        label='标签'
        options={tags.map((tag) => ({
          value: tag.name,
          label: tag.name,
          count: tag.count,
        }))}
        selected={filters.tagNames}
        onChange={(tagNames) => onChange({ tagNames })}
      />

      <MultiSelect
        label='语言'
        options={languages.map((language) => ({
          value: language,
          label: language,
        }))}
        selected={filters.languages}
        onChange={(selected) => onChange({ languages: selected })}
        emptyText='暂无语言数据'
      />

      <Select
        value={filters.starRange}
        onValueChange={(value) =>
          onChange({ starRange: value as RepoFilters['starRange'] })
        }
      >
        <SelectTrigger size='sm' className='w-32'>
          <SelectValue placeholder='全部 Star' />
        </SelectTrigger>
        <SelectContent>
          {STAR_RANGE_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={filters.timeRange}
        onValueChange={(value) =>
          onChange({ timeRange: value as RepoFilters['timeRange'] })
        }
      >
        <SelectTrigger size='sm' className='w-32'>
          <SelectValue placeholder='全部时间' />
        </SelectTrigger>
        <SelectContent>
          {TIME_RANGE_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <div className='ms-auto flex items-center gap-2'>
        {activeCount > 0 && (
          <Badge variant='secondary' className='font-normal'>
            已选 {activeCount} 项条件
          </Badge>
        )}
        <Select
          value={filters.sort}
          onValueChange={(value) =>
            onChange({ sort: value as RepoFilters['sort'] })
          }
        >
          <SelectTrigger size='sm' className='w-32'>
            <SelectValue placeholder='排序' />
          </SelectTrigger>
          <SelectContent>
            {SORT_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                按{option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant='outline'
          size='sm'
          className='h-8'
          onClick={() =>
            onChange({ order: filters.order === 'asc' ? 'desc' : 'asc' })
          }
          title={
            filters.order === 'asc'
              ? '当前升序，点击切换降序'
              : '当前降序，点击切换升序'
          }
        >
          {filters.order === 'asc' ? <ArrowUp /> : <ArrowDown />}
          {filters.order === 'asc' ? '升序' : '降序'}
        </Button>
        {activeCount > 0 && (
          <Button variant='ghost' size='sm' className='h-8' onClick={onReset}>
            <RotateCcw />
            清除
          </Button>
        )}
      </div>
    </div>
  )
}
