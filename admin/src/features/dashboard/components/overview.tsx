import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis } from 'recharts'

/** 近 12 个月累计 Star 数（演示数据，接入后端后由 /api/dashboard/stats 提供） */
const data = [
  { name: '1月', total: 3240 },
  { name: '2月', total: 3620 },
  { name: '3月', total: 4050 },
  { name: '4月', total: 4410 },
  { name: '5月', total: 4870 },
  { name: '6月', total: 5240 },
  { name: '7月', total: 5680 },
  { name: '8月', total: 6120 },
  { name: '9月', total: 6540 },
  { name: '10月', total: 7010 },
  { name: '11月', total: 7480 },
  { name: '12月', total: 7960 },
]

export function Overview() {
  return (
    <ResponsiveContainer width='100%' height={350}>
      <BarChart data={data}>
        <XAxis
          dataKey='name'
          stroke='#888888'
          fontSize={12}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          direction='ltr'
          stroke='#888888'
          fontSize={12}
          tickLine={false}
          axisLine={false}
        />
        <Bar
          dataKey='total'
          fill='currentColor'
          radius={[4, 4, 0, 0]}
          className='fill-primary'
        />
      </BarChart>
    </ResponsiveContainer>
  )
}
