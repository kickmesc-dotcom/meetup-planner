import type { ReactNode } from "react";

/**
 * Поле формы: подпись, звёздочка, подсказка и ошибка — в одном месте.
 *
 * Зачем компонент. В формах входа, сброса и кабинета одно и то же собиралось
 * руками, и связь `aria-describedby` то была, то нет: ошибка у поля читалась
 * скринридером как отдельный текст ниже формы, а звёздочка обязательности
 * оставалась загадкой. Один компонент держит три обещания сразу:
 *
 *  - у поля есть имя (`label htmlFor`), и его видно, а не только в дереве;
 *  - подсказка и ошибка связаны через `aria-describedby`, ошибка ещё и
 *    объявляется (`role="alert"`);
 *  - `aria-invalid`/`aria-required` выставляются по состоянию, а не забываются.
 *
 * Почему render-prop, а не готовый `<input>`. Полю иногда нужен сосед внутри
 * той же рамки: кнопка «показать пароль», кнопка «сохранить» рядом с доменом.
 * Функция отдаёт только ARIA-связи и `id`, разметку поля решает вызывающий.
 */
export interface FieldA11y {
  id: string;
  "aria-required": true | undefined;
  "aria-invalid": true | undefined;
  "aria-describedby": string | undefined;
}

export interface FormFieldProps {
  id: string;
  label: ReactNode;
  required?: boolean;
  /** Ошибка уже есть, но рендерится снаружи (общая ошибка формы). */
  invalid?: boolean;
  hint?: ReactNode;
  error?: ReactNode;
  /** Внешние id описания — например, общий блок ошибки формы. */
  describedBy?: string;
  /** Свой id ошибки, когда он уже используется в тестах или ссылках. */
  errorId?: string;
  className?: string;
  labelClassName?: string;
  children: (field: FieldA11y) => ReactNode;
}

export default function FormField({
  id,
  label,
  required = false,
  invalid = false,
  hint,
  error,
  describedBy,
  errorId,
  className,
  labelClassName,
  children,
}: FormFieldProps) {
  const hintId = hint ? `${id}-hint` : undefined;
  const ownErrorId = error ? (errorId ?? `${id}-error`) : undefined;
  const described = [describedBy, hintId, ownErrorId].filter(Boolean).join(" ");

  return (
    <div className={className}>
      <label
        htmlFor={id}
        className={labelClassName ?? "block text-xs text-tg-text"}
      >
        {label}
        {required && (
          <>
            {" "}
            <span aria-hidden>*</span>
          </>
        )}
      </label>
      {children({
        id,
        "aria-required": required ? true : undefined,
        "aria-invalid": invalid || !!error ? true : undefined,
        "aria-describedby": described || undefined,
      })}
      {hint && (
        <p id={hintId} className="mt-1 text-2xs text-tg-hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={ownErrorId} role="alert" className="mt-1 text-2xs text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}
