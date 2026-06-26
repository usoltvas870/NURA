import { ReactNode } from 'react';

export interface AppHeaderProps {
  /** Optional centered page title (Playfair Display, 20px). Omit on the home screen. */
  title?: string;
  /** Right-side action buttons, typically one `<IconButton>` */
  actions?: ReactNode;
  /** href for the NURA logo link @default "#" */
  logoHref?: string;
}

export interface IconButtonProps {
  /** Tabler icon class suffix, e.g. "ti-sun-moon", "ti-bell", "ti-settings" */
  icon: string;
  label?: string;
  onClick?: () => void;
}

export declare function AppHeader(props: AppHeaderProps): JSX.Element;
export declare function IconButton(props: IconButtonProps): JSX.Element;
