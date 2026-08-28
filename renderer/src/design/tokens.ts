export type ThemeName = 'midnight' | 'frost';

export type Theme = {
  canvas: string;
  map: string;
  panel: string;
  surface: string;
  border: string;
  grid: string;
  text: string;
  textSecondary: string;
  textMuted: string;
  dataMissing: string;
  routeInactive: string;
  route: string;
  routeHighlight: string;
  speed: string;
  heartRate: string;
  distance: string;
  temperature: string;
  elevation: string;
  power: string;
  grade: string;
};

export const themes: Record<ThemeName, Theme> = {
  midnight: {
    canvas: '#050505',
    map: '#080808',
    panel: '#0A0A0A',
    surface: 'rgba(12, 12, 12, 0.68)',
    border: 'rgba(255, 255, 255, 0.13)',
    grid: 'rgba(255, 255, 255, 0.045)',
    text: '#F4F4F1',
    textSecondary: '#B6B6B0',
    textMuted: '#72726D',
    dataMissing: '#D7D7D0',
    routeInactive: '#333330',
    route: '#FF4D00',
    routeHighlight: '#FFF7F2',
    speed: '#F4F4F1',
    heartRate: '#FF4F5E',
    distance: '#F4F4F1',
    temperature: '#A6A6A0',
    elevation: '#F4F4F1',
    power: '#F4F4F1',
    grade: '#A6A6A0',
  },
  frost: {
    canvas: '#F2F2EF',
    map: '#EAEAE6',
    panel: '#F7F7F4',
    surface: 'rgba(248, 248, 245, 0.66)',
    border: 'rgba(0, 0, 0, 0.16)',
    grid: 'rgba(0, 0, 0, 0.055)',
    text: '#11110F',
    textSecondary: '#494946',
    textMuted: '#7B7B75',
    dataMissing: '#2F2F2C',
    routeInactive: '#B8B8B1',
    route: '#F04400',
    routeHighlight: '#11110F',
    speed: '#11110F',
    heartRate: '#D9283F',
    distance: '#11110F',
    temperature: '#666660',
    elevation: '#11110F',
    power: '#11110F',
    grade: '#666660',
  },
};
