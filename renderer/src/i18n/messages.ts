export type Locale = 'en' | 'pt-BR';

const messages = {
  en: {
    speed: 'Speed',
    averageSpeed: 'Avg speed',
    heartRate: 'Heart rate',
    averageHeartRate: 'Avg heart rate',
    power: 'Power',
    temperature: 'Temperature',
    distance: 'Distance',
    ascent: 'Elevation',
    altitude: 'Altitude',
    maximumAltitude: 'Max altitude',
    totalTime: 'Total time',
    elevationProfile: 'Elevation profile',
    grade: 'Grade',
    maximumGrade: 'Max grade',
    averageTemperature: 'Avg temperature',
    averagePower: 'Avg power',
    progress: 'Route progress',
  },
  'pt-BR': {
    speed: 'Velocidade',
    averageSpeed: 'Velocidade média',
    heartRate: 'Frequência cardíaca',
    averageHeartRate: 'FC média',
    power: 'Potência',
    temperature: 'Temperatura',
    distance: 'Distância',
    ascent: 'Elevação',
    altitude: 'Altitude',
    maximumAltitude: 'Altitude máxima',
    totalTime: 'Tempo total',
    elevationProfile: 'Perfil de elevação',
    grade: 'Inclinação',
    maximumGrade: 'Inclinação máx.',
    averageTemperature: 'Temp. média',
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
