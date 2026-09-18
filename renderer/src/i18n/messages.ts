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
    minimalSpeed: 'SPEED',
    minimalDistance: 'DISTANCE',
    minimalHeartRate: 'HEART RATE',
    minimalElevation: 'ELEVATION',
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
    minimalSpeed: 'VELOCIDADE',
    minimalDistance: 'DISTÂNCIA',
    minimalHeartRate: 'FREQUÊNCIA',
    minimalElevation: 'ALTIMETRIA',
  },
} as const;

export const createI18n = (locale: Locale) => ({
  t: (key: keyof (typeof messages)['en']) => messages[locale][key],
  number: (value: number, decimals = 0) =>
    new Intl.NumberFormat(locale, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(value),
  date: (value: string) => {
    // Python sends the activity calendar date as an ISO prefix (the catalog
    // timestamp rendered in the database session timezone). Format that date
    // directly instead of shifting it through a UTC instant, which would show
    // the previous day for rides started just after local midnight.
    const calendarDate = /^(\d{4}-\d{2}-\d{2})/.exec(value)?.[1];
    const parsed = calendarDate ? new Date(`${calendarDate}T00:00:00Z`) : new Date(value);
    return new Intl.DateTimeFormat(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC',
    }).format(parsed);
  },
});
