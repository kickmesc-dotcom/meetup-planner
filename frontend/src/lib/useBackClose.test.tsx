// @vitest-environment jsdom
/**
 * Системная «назад» закрывает оверлей, а не приложение.
 *
 * Причина: карточка коллеги и дашборд отдела открывались только с собственной
 * стрелкой. На телефоне человек жмёт «назад» — и выходит из мини-аппа целиком,
 * вместо того чтобы вернуться к ленте с прежними фильтрами.
 *
 * Проверяем ровно три свойства: шаг истории добавляется при открытии, `popstate`
 * вызывает закрытие, а закрытие своей стрелкой снимает добавленный шаг (иначе
 * следующее «назад» снова открывало бы карточку).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { useBackClose } from "./useBackClose";

function Overlay({ onClose }: { onClose: () => void }) {
  useBackClose(onClose);
  return <div>оверлей</div>;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("useBackClose", () => {
  it("добавляет шаг истории при открытии", () => {
    const push = vi.spyOn(window.history, "pushState").mockImplementation(() => {});
    render(<Overlay onClose={() => {}} />);

    expect(push).toHaveBeenCalledTimes(1);
    expect(push.mock.calls[0]?.[0]).toMatchObject({ semitaskOverlay: true });
  });

  it("по системной «назад» закрывает оверлей", () => {
    vi.spyOn(window.history, "pushState").mockImplementation(() => {});
    const onClose = vi.fn();
    render(<Overlay onClose={onClose} />);

    window.dispatchEvent(new PopStateEvent("popstate"));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("закрытие стрелкой снимает свой шаг истории", () => {
    vi.spyOn(window.history, "pushState").mockImplementation(() => {});
    const back = vi.spyOn(window.history, "back").mockImplementation(() => {});
    const view = render(<Overlay onClose={() => {}} />);

    view.unmount();

    expect(back).toHaveBeenCalledTimes(1);
  });

  it("после «назад» не снимает шаг второй раз", () => {
    vi.spyOn(window.history, "pushState").mockImplementation(() => {});
    const back = vi.spyOn(window.history, "back").mockImplementation(() => {});
    const view = render(<Overlay onClose={() => {}} />);

    window.dispatchEvent(new PopStateEvent("popstate"));
    view.unmount();

    expect(back).not.toHaveBeenCalled();
  });
});
