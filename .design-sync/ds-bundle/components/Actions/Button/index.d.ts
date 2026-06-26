import { ReactNode, MouseEventHandler } from 'react';

export interface ButtonProps {
  /**
   * Visual variant:
   *  - "primary"  — terra fill, white text, shadow (default CTA on any surface)
   *  - "ghost"    — transparent with white border (CTA on dark/photo backgrounds)
   *  - "ghost-sm" — pill-shaped small ghost (share/action in photo card footer)
   *  - "soft"     — light fill with border (secondary action on light surface)
   *  - "chat"     — same as primary, used for send/chat actions
   */
  variant?: 'primary' | 'ghost' | 'ghost-sm' | 'soft' | 'chat';
  /** Stretch to 100% container width */
  full?: boolean;
  /** Show spinner and hide label */
  loading?: boolean;
  disabled?: boolean;
  onClick?: MouseEventHandler<HTMLButtonElement>;
  children?: ReactNode;
}

export declare function Button(props: ButtonProps): JSX.Element;
