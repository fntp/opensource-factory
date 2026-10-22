import { ContentSection } from '../components/content-section'
import { NotificationsForm } from './notifications-form'

export function SettingsNotifications() {
  return (
    <ContentSection
      title='推送偏好'
      desc='设置每日推荐推送的时间、阈值与通道开关。'
    >
      <NotificationsForm />
    </ContentSection>
  )
}
