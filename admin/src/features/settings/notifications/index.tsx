import { ContentSection } from '../components/content-section'
import { NotificationsForm } from './notifications-form'
import { TelegramBotPanel } from './telegram-bot-panel'

export function SettingsNotifications() {
  return (
    <ContentSection
      title='推送偏好'
      desc='设置每日推荐推送的时间、阈值与通道开关，并管理 Telegram 查询 Bot。'
    >
      <div className='space-y-8'>
        <NotificationsForm />
        <TelegramBotPanel />
      </div>
    </ContentSection>
  )
}
