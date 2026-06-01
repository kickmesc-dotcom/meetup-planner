import SubScreen from "./SubScreen";
import { ScheduleBody } from "./RandomPhrasesScheduleScreen";
import { GeneratorBody } from "./RandomPhrasesGeneratorScreen";

interface Props {
  onBack: () => void;
}

// GHG7 P2.3.b: объединённый экран рандомных фраз. Раньше были два пункта меню —
// «Автопост рандомных фраз» (когда постить: расписание + тогл) и «Генератор
// фраз» (что постить: длина/история/шансы). Теперь одна Card → один экран с
// двумя секциями. Тела вынесены из исходных экранов (ScheduleBody/GeneratorBody),
// каждое со своим query/мутацией — состояние не делится, бэкенд-контракты те же.
export default function RandomPhrasesScreen({ onBack }: Props) {
  return (
    <SubScreen
      title="💬 Рандомные фразы"
      subtitle="Расписание автопоста + параметры генератора"
      onBack={onBack}
    >
      <ScheduleBody />
      <GeneratorBody />
    </SubScreen>
  );
}
