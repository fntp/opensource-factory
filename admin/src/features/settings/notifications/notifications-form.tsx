import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Loader2, RotateCcw, Save } from 'lucide-react'
import { toast } from 'sonner'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  CHANNEL_DESCRIPTIONS,
  CHANNEL_KEYS,
  CHANNEL_LABELS,
  DEFAULT_PUSH_PREFERENCES,
  TIMEZONE_OPTIONS,
  type ChannelKey,
  type PushPreferences,
  describePushPreferences,
  fetchPushPreferences,
  savePushPreferences,
  validatePushPreferences,
} from './api'

function PreferenceRow({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <div className='flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between'>
      <div className='space-y-0.5'>
        <Label className='text-base'>{title}</Label>
        <p className='text-sm text-muted-foreground'>{description}</p>
      </div>
      {children}
    </div>
  )
}

export function NotificationsForm() {
  const { data, isLoading } = useQuery({
    queryKey: ['push-preferences'],
    queryFn: fetchPushPreferences,
  })
  const [draft, setDraft] = useState<PushPreferences | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  // 未编辑时跟随接口数据；一旦用户修改，draft 优先（避免 effect 同步状态）。
  const preferences = draft ?? data?.preferences ?? DEFAULT_PUSH_PREFERENCES

  function patch(changes: Partial<PushPreferences>) {
    setDraft((current) => ({ ...(current ?? preferences), ...changes }))
  }

  function toggleChannel(key: ChannelKey, checked: boolean) {
    setDraft((current) => {
      const base = current ?? preferences
      return { ...base, channels: { ...base.channels, [key]: checked } }
    })
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const validation = validatePushPreferences(preferences)
    setErrors(validation)
    if (validation.length > 0) return

    setSaving(true)
    try {
      const payload = await savePushPreferences(preferences)
      setDraft(payload.preferences)
      toast.success('推送偏好已保存')
    } catch {
      toast.error('保存失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  if (isLoading) {
    return (
      <div className='flex items-center gap-2 py-8 text-sm text-muted-foreground'>
        <Loader2 className='size-4 animate-spin' />
        正在加载推送偏好…
      </div>
    )
  }

  const enabledChannels = CHANNEL_KEYS.filter((key) => preferences.channels[key])
  const timezoneOptions = (TIMEZONE_OPTIONS as readonly string[]).includes(
    preferences.timezone
  )
    ? TIMEZONE_OPTIONS
    : [preferences.timezone, ...TIMEZONE_OPTIONS]

  return (
    <form onSubmit={handleSubmit} className='space-y-6'>
      <div className='flex flex-wrap items-center gap-2 text-sm text-muted-foreground'>
        <Badge variant={preferences.enabled ? 'default' : 'secondary'}>
          {preferences.enabled ? '已启用' : '已暂停'}
        </Badge>
        <span>{describePushPreferences(preferences)}</span>
        {data?.isDefault && draft === null ? (
          <Badge variant='outline'>当前使用默认设置</Badge>
        ) : null}
      </div>

      <PreferenceRow
        title='每日推荐推送'
        description='关闭后不会自动推送任何推荐，仍可手动触发。'
      >
        <Switch
          checked={preferences.enabled}
          onCheckedChange={(checked) => patch({ enabled: checked })}
          aria-label='启用每日推荐推送'
        />
      </PreferenceRow>

      <div className='grid gap-4 sm:grid-cols-2'>
        <div className='space-y-2'>
          <Label htmlFor='push-time'>推送时间</Label>
          <Input
            id='push-time'
            type='time'
            value={preferences.timeOfDay}
            onChange={(event) => patch({ timeOfDay: event.target.value })}
            aria-invalid={!preferences.timeOfDay}
          />
          <p className='text-xs text-muted-foreground'>
            按下方时区每天在该时刻前后 10 分钟内推送。
          </p>
        </div>
        <div className='space-y-2'>
          <Label htmlFor='push-timezone'>时区</Label>
          <Select
            value={preferences.timezone}
            onValueChange={(value) => patch({ timezone: value })}
          >
            <SelectTrigger id='push-timezone' className='w-full'>
              <SelectValue placeholder='选择时区' />
            </SelectTrigger>
            <SelectContent>
              {timezoneOptions.map((timezone) => (
                <SelectItem key={timezone} value={timezone}>
                  {timezone}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className='text-xs text-muted-foreground'>
            推送时间按此 IANA 时区解释。
          </p>
        </div>
      </div>

      <div className='grid gap-4 sm:grid-cols-2'>
        <div className='space-y-2'>
          <Label htmlFor='min-score'>匹配度阈值</Label>
          <Input
            id='min-score'
            type='number'
            min={0}
            max={1}
            step={0.05}
            value={preferences.minScore}
            onChange={(event) => patch({ minScore: Number(event.target.value) })}
          />
          <p className='text-xs text-muted-foreground'>
            低于该匹配度（0~1）的推荐不推送，默认 0.35。
          </p>
        </div>
        <div className='space-y-2'>
          <Label htmlFor='min-quality-score'>质量分阈值</Label>
          <Input
            id='min-quality-score'
            type='number'
            min={0}
            max={1}
            step={0.05}
            value={preferences.minQualityScore}
            onChange={(event) =>
              patch({ minQualityScore: Number(event.target.value) })
            }
          />
          <p className='text-xs text-muted-foreground'>
            低于该质量分（0~1）的推荐不推送，默认 0.55。
          </p>
        </div>
      </div>

      <div className='space-y-3'>
        <div>
          <h3 className='text-base font-medium'>推送通道</h3>
          <p className='text-sm text-muted-foreground'>
            至少开启一个通道；未配置的通道会在发送时自动跳过。
          </p>
        </div>
        {CHANNEL_KEYS.map((key) => (
          <PreferenceRow
            key={key}
            title={CHANNEL_LABELS[key]}
            description={CHANNEL_DESCRIPTIONS[key]}
          >
            <Switch
              checked={preferences.channels[key]}
              onCheckedChange={(checked) => toggleChannel(key, checked)}
              aria-label={`启用${CHANNEL_LABELS[key]}`}
            />
          </PreferenceRow>
        ))}
        {enabledChannels.length === 0 ? (
          <Alert variant='destructive'>
            <AlertCircle />
            <AlertDescription>
              未开启任何推送通道，定时任务将跳过你的推荐。
            </AlertDescription>
          </Alert>
        ) : null}
      </div>

      {errors.length > 0 ? (
        <Alert variant='destructive'>
          <AlertCircle />
          <AlertDescription>
            <ul className='list-disc space-y-1 pl-4'>
              {errors.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      <div className='flex flex-wrap items-center gap-2'>
        <Button type='submit' disabled={saving}>
          {saving ? (
            <Loader2 className='size-4 animate-spin' />
          ) : (
            <Save className='size-4' />
          )}
          保存偏好
        </Button>
        <Button
          type='button'
          variant='outline'
          disabled={saving}
          onClick={() => {
            setDraft({
              ...DEFAULT_PUSH_PREFERENCES,
              channels: { ...DEFAULT_PUSH_PREFERENCES.channels },
            })
            setErrors([])
            toast.info('已恢复默认值，点击保存后生效')
          }}
        >
          <RotateCcw className='size-4' />
          恢复默认
        </Button>
      </div>
    </form>
  )
}
