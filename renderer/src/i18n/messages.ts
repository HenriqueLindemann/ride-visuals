export type Locale = 'en' | 'pt-BR';

const messages = {
  en: {
    speed: 'Speed',
    averageSpeed: 'Average speed',
    heartRate: 'Heart rate',
    averageHeartRate: 'Average heart rate',
    power: 'Power',
    temperature: 'Temperature',
    distance: 'Distance covered',
    ascent: 'Elevation gain',
    altitude: 'Altitude',
    maximumAltitude: 'Maximum altitude',
    totalTime: 'Total time',
    elevationProfile: 'Elevation profile',
    grade: 'Grade',
    maximumGrade: 'Maximum grade',
    averageTemperature: 'Average temperature',
    averagePower: 'Average power',
    progress: 'Route progress',
  },
  'pt-BR': {
    speed: 'Velocidade',
    averageSpeed: 'Velocidade média',
    heartRate: 'Frequência cardíaca',
    averageHeartRate: 'Frequência cardíaca média',
    power: 'Potência',
    temperature: 'Temperatura',
    distance: 'Distância percorrida',
    ascent: 'Ganho de elevação',
    altitude: 'Altitude',
    maximumAltitude: 'Altitude máxima',
    totalTime: 'Tempo total',
    elevationProfile: 'Perfil de elevação',
    grade: 'Inclinação',
    maximumGrade: 'Inclinação máxima',
    averageTemperature: 'Temperatura média',
    averagePower: 'Potência média',
    progress: 'Progresso da rota',
  },
} as const;

export const createI18n = (locale: Locale) => ({
  t: (key: keyof (typeof messages)['en']) => messages[locale][key],
  number: (value: number, decimals = 0) =>
    new Intl.NumberFormat(locale, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(value),
  date: (value: string) =>
    new Intl.DateTimeFormat(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC',
    }).format(new Date(value)),
});
