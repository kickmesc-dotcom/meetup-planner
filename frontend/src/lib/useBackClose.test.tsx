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
import { resetBackCloseGuard, useBackClose } from "./useBackClose";

function Overlay({ onClose }: { onClose: () => void }) {
  useBackClose(onClose);
  return <div>оверлей</div>;
}

afterEach(() => {
  cleanup();
  resetBackCloseGuard();
  vi.restoreAllMocks();
});

describe("useBackClose", () => {
  it("добавляет шаг истории при открытии", () => {
    const push = vi.spyOn(window.history, "pushState").mockImplementation(() => {});
    render(<Overlay onClose={() => {}} />);

    expect(push).toHaveBeenCalledTimes(1);
    expect(push.mock.calls[0]?.[0]).toMatchObject({
      semitaskOverlay: expect.stringMatching(/^overlay-\d+$/),
    });
  });

  it("по системной «назад» закрывает оверлей", () => {
    vi.spyOn(window.history, "pushState").mockImplementation(() => {});
    const onClose = vi.fn();
    render(<Overlay onClose={onClose} />);

    window.dispatchEvent(new PopStateEvent("popstate"));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("не закрывает экран от чужого popstate — шаг снял другой оверлей", () => {
    vi.spyOn(window.history, "pushState").mockImplementation(() => {});
    const onClose = vi.fn();
    render(<Overlay onClose={onClose} />);

    // Метка другого экземпляра: это уборка соседнего оверлея, а не жест
    // человека. Раньше такой popstate закрывал только что открытый экран.
    window.dispatchEvent(
      new PopStateEvent("popstate", {
        state: { semitaskOverlay: "overlay-999999" },
      }),
    );
    expect(onClose).not.toHaveBeenCalled();

    window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("закрытие стрелкой снимает свой шаг истории", () => {
    // pushState не мокаем: хук снимает шаг только пока `history.state` ещё его,
    // и подмена истории лишила бы тест смысла.
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
