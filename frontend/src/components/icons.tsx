// V7.1 icons -- direct port of `frontend-prototype/src/components/icons.js`.
// Carbon-style 16/20px SVGs as React components.

import type { CSSProperties, SVGProps } from 'react';

interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'size'> {
  size?: number;
  className?: string;
  style?: CSSProperties;
}

const makeIcon =
  (path: string, viewBox = '0 0 16 16') =>
  ({ size = 16, className = 'cds-icon', ...rest }: IconProps) => (
    <svg
      width={size}
      height={size}
      viewBox={viewBox}
      className={className}
      fill="currentColor"
      {...rest}
    >
      <path d={path} />
    </svg>
  );

export const I = {
  Menu: makeIcon('M2 11h12v1H2zM2 7h12v1H2zM2 3h12v1H2z'),
  Close: makeIcon(
    'M12 4.7L11.3 4 8 7.3 4.7 4 4 4.7 7.3 8 4 11.3 4.7 12 8 8.7 11.3 12 12 11.3 8.7 8z',
  ),
  Bell: makeIcon(
    'M14 11l-1-.6V7a5 5 0 00-4-4.9V1H7v1.1A5 5 0 003 7v3.4L2 11v2h4a2 2 0 004 0h4zM4 7a4 4 0 018 0v3.4l1 .6H3l1-.6zm4 7a1 1 0 01-1-1h2a1 1 0 01-1 1z',
  ),
  User: makeIcon(
    'M8 1a3 3 0 100 6 3 3 0 000-6zm0 5a2 2 0 110-4 2 2 0 010 4zm5 9v-1a4 4 0 00-4-4H7a4 4 0 00-4 4v1h1v-1a3 3 0 013-3h2a3 3 0 013 3v1z',
  ),
  Dashboard: makeIcon(
    'M2 2v6h6V2H2zm5 5H3V3h4v4zM8 8v6h6V8H8zm5 5H9V9h4v4zM2 8v6h5V8H2zm4 5H3V9h3v4zM8 2v5h6V2H8zm5 4H9V3h4v3z',
  ),
  ListChecked: makeIcon(
    'M14 7H7v1h7zM14 12H7v1h7zM14 2H7v1h7zM4.4 5.4L2.7 3.7 2 4.4l2.4 2.4L7 4.2l-.7-.7zM4.4 10.4L2.7 8.7 2 9.4l2.4 2.4L7 9.2l-.7-.7zM4.4 15.4L2.7 13.7 2 14.4l2.4 2.4L7 14.2l-.7-.7z',
    '0 0 18 18',
  ),
  Box: makeIcon('M14 2H2v12h12V2zM3 3h10v10H3V3z'),
  Chart: makeIcon(
    'M14 13H3V2H2v12h12v-1zM12.4 5.4L9 8.7 6.6 6.4 4 9l.7.7L6.6 7.8 9 10.1l4-4z',
  ),
  Document: makeIcon('M9 1H3v14h10V5l-4-4zm0 1.4L11.6 5H9V2.4zM4 14V2h4v4h4v8H4z'),
  Settings: makeIcon(
    'M13.5 8.4L14.8 7l-2.6-2.6-1.3 1.3a3.5 3.5 0 00-1.4-.6V3.3H5.5v1.8a3.5 3.5 0 00-1.4.6L2.8 4.4 0.2 7l1.3 1.4a3.5 3.5 0 00-.6 1.4H-1v4h1.8a3.5 3.5 0 00.6 1.4l-1.3 1.3 2.6 2.6 1.3-1.3a3.5 3.5 0 001.4.6V20h4v-1.8a3.5 3.5 0 001.4-.6l1.3 1.3 2.6-2.6-1.3-1.3a3.5 3.5 0 00.6-1.4H17v-4h-1.8a3.5 3.5 0 00-.7-1.2zM7.5 12a2 2 0 110-4 2 2 0 010 4z',
    '0 0 16 18',
  ),
  Add: makeIcon('M9 7V3H7v4H3v2h4v4h2V9h4V7H9z'),
  Search: makeIcon(
    'M11.6 11.1l3.4 3.4-.7.7-3.4-3.4a5.5 5.5 0 11.7-.7zM7.5 12a4.5 4.5 0 100-9 4.5 4.5 0 000 9z',
  ),
  Filter: makeIcon(
    'M14 2H2v2.4l4.5 4.5V14l3-2v-3l4.5-4.6V2zM9 8.4L8.7 9H7.3L7 8.4 3 4.4V3h10v1.4L9 8.4z',
  ),
  Renew: makeIcon(
    'M14 8a6 6 0 11-1.8-4.3l-1.3 1.3H14V1.4l-1.3 1.3A7 7 0 008 1a7 7 0 107 7h-1z',
  ),
  Download: makeIcon('M11.4 8.6L9 11V2H7v9L4.6 8.6 4 9.3 8 13l4-3.7zM2 14h12v1H2z'),
  Upload: makeIcon('M8 2L4 5.7l.6.7L7 4v9h2V4l2.4 2.4.7-.7zM2 14h12v1H2z'),
  Edit: makeIcon(
    'M14 1.7L13.3 1l-1.3 1.3L13.3 4 14 3.3l-1.3-1.3 1.3-1.3zm-2 2.6L10.7 3 1 12.7V15h2.3L13 5.3l-1-1zM3 14H2v-1l8-8 1 1-8 8z',
  ),
  Trash: makeIcon(
    'M5 7v6h1V7H5zm3 0v6h1V7H8zm3 0v6h1V7h-1zM4 4v10a1 1 0 001 1h7a1 1 0 001-1V4h-9zm1 1h7v9H5V5zM10 2V1H7v1H4v1h10V2h-4z',
  ),
  Copy: makeIcon('M11 1H3v10h2v2h8V3h-2V1zm-1 1v2H4v6h7V2h-1zM5 12V5h6v7H5z'),
  ChevronRight: makeIcon('M6 11.6L9.6 8 6 4.4 6.7 3.7 11 8 6.7 12.3z'),
  ChevronDown: makeIcon('M8 11l-4-4 .7-.7L8 9.6l3.3-3.3.7.7z'),
  ChevronLeft: makeIcon('M10 4.4L6.4 8 10 11.6l-.7.7L5 8l4.3-4.3z'),
  CaretDown: makeIcon('M8 11L3 6h10z'),
  More: makeIcon(
    'M9 8a1 1 0 11-2 0 1 1 0 012 0zM9 13a1 1 0 11-2 0 1 1 0 012 0zM9 3a1 1 0 11-2 0 1 1 0 012 0z',
  ),
  Check: makeIcon('M6.7 12.3L3 8.5 3.7 7.8 6.7 10.8 12.3 5.2 13 5.9z'),
  Warning: makeIcon('M8 1L0 15h16L8 1zm0 2.4L13.5 13H2.5L8 3.4zM7 6h2v4H7V6zm0 5h2v2H7v-2z'),
  Error: makeIcon(
    'M8 1a7 7 0 100 14A7 7 0 008 1zm0 13A6 6 0 118 2a6 6 0 010 12zm-1-4h2v2H7v-2zm0-6h2v5H7V4z',
  ),
  Info: makeIcon(
    'M8 1a7 7 0 100 14A7 7 0 008 1zm0 13A6 6 0 118 2a6 6 0 010 12zm-1-4h2v-3H7v3zm0-5h2V4H7v1z',
  ),
  Success: makeIcon(
    'M8 1a7 7 0 100 14A7 7 0 008 1zm-1 10L4 8l.7-.7L7 9.6l4.3-4.3.7.7L7 11z',
  ),
  Logout: makeIcon(
    'M11.7 8.7L7.4 13l-.7-.7L9.6 9.5H1v-1h8.6L6.7 5.5l.7-.7L11.7 9zM13 1H6v6h1V2h6v12H7v-5H6v6h7V1z',
  ),
  Lock: makeIcon('M12 7V5a4 4 0 00-8 0v2H3v8h10V7h-1zM5 5a3 3 0 116 0v2H5V5zm7 9H4V8h8v6z'),
  View: makeIcon(
    'M8 3C3.5 3 1 8 1 8s2.5 5 7 5 7-5 7-5-2.5-5-7-5zm0 8a3 3 0 110-6 3 3 0 010 6zm0-1a2 2 0 100-4 2 2 0 000 4z',
  ),
  ArrowRight: makeIcon('M11.3 7.5L7 3.2 6.3 4 9.3 7H2v1h7.3l-3 3 .7.7 4.3-4.2z'),
  ArrowUp: makeIcon('M8 2.7L3.7 7l.7.7L7.5 4.6V14h1V4.6l3.1 3.1.7-.7z'),
  ArrowDown: makeIcon('M8.5 11.4l3.1-3.1.7.7L8 13.3 3.7 9l.7-.7L7.5 11.4V2h1z'),
  Save: makeIcon('M14 1H2v14h12V1zM3 2h2v4h6V2h2v12H3V2zm6 0v3H7V2h2z'),
  PlayFilled: makeIcon('M3 2v12l11-6z'),
  Pause: makeIcon('M5 3h2v10H5zM9 3h2v10H9z'),
  Stop: makeIcon('M3 3h10v10H3z'),
  Sun: makeIcon(
    'M8 4.5a3.5 3.5 0 100 7 3.5 3.5 0 000-7zm0 6a2.5 2.5 0 110-5 2.5 2.5 0 010 5zM7.5 1h1v2h-1zM7.5 13h1v2h-1zM1 7.5h2v1H1zM13 7.5h2v1h-2zM2.6 3.3l.7-.7L4.7 4 4 4.7zm9 9l.7-.7 1.4 1.4-.7.7zM2.6 12.7L4 11.3l.7.7-1.4 1.4zm9-9L13 2.3l.7.7-1.4 1.4z',
  ),
  Moon: makeIcon(
    'M9.5 14.5A6.5 6.5 0 013 8a6.5 6.5 0 014.5-6.2A5 5 0 009.5 12a5 5 0 004.7-3.2A6.5 6.5 0 019.5 14.5z',
  ),
  Contrast: makeIcon('M8 1a7 7 0 100 14A7 7 0 008 1zM2 8a6 6 0 016-6v12a6 6 0 01-6-6z'),
  Receipt: makeIcon(
    'M3 1v14l1.5-1L6 15l1.5-1L9 15l1.5-1L12 15l1-1V1l-1 1-1.5-1L9 2 7.5 1 6 2 4.5 1zm1 1.5l.5.3L6 2l1.5.8.5-.3.5.3L9.5 2 11 2.8l.5-.3.5.3v11l-.5-.3-.5.3-1.5-.8-.5.3-.5-.3L7 13.8l-.5-.3-.5.3-1.5-.8-.5.3-.5-.3v-11zM5 5h6v1H5zM5 7h6v1H5zM5 9h4v1H5z',
  ),
};

export type IconComponent = (typeof I)[keyof typeof I];
