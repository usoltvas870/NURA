import { ReactNode, CSSProperties } from 'react';

export interface CardProps {
  /**
   * Accent notch:
   *  - "top"  — 3px sage green top border (info/recommendation blocks)
   *  - "left" — 3px sage green left border, squared left corners (disclaimer blocks)
   *  - undefined — plain card
   */
  accent?: 'top' | 'left';
  /** Whether to add standard 20px padding inside. @default true */
  padding?: boolean;
  children?: ReactNode;
  style?: CSSProperties;
}

export declare function Card(props: CardProps): JSX.Element;
