import { useMutation, useQueryClient } from "@tanstack/react-query";
import { likeVoiceSubmission } from "@/api/game";
import { haptic } from "@/tg/webapp";

/**
 * GHG11: лайк варианта голосового задания (toggle на сервере).
 *
 * Общий для раскрытой карточки ленты и панели активностей. Счётчик берём из
 * ответа мутации (фолбэк — исходные значения), а список инвалидируем, чтобы
 * соседние карточки увидели новый счётчик.
 */
export default function VoiceLikeButton({
  submissionId,
  initialLiked,
  initialLikes,
  invalidateKey,
}: {
  submissionId: number;
  initialLiked: boolean;
  initialLikes: number;
  invalidateKey?: string;
}) {
  const qc = useQueryClient();
  const like = useMutation({
    mutationFn: () => likeVoiceSubmission(submissionId),
    onSuccess: () => {
      haptic("success");
      if (invalidateKey) void qc.invalidateQueries({ queryKey: [invalidateKey] });
    },
    onError: () => haptic("error"),
  });
  const liked = like.data?.liked ?? initialLiked;
  const likes = like.data?.likes ?? initialLikes;

  return (
    <button
      type="button"
      disabled={like.isPending}
      onClick={(e) => {
        e.stopPropagation();
        haptic("light");
        like.mutate();
      }}
      className={[
        "shrink-0 rounded-full px-2 py-1 text-xs disabled:opacity-60",
        liked ? "bg-status-busy/20 text-status-busy" : "bg-tg-secondary-bg text-tg-hint",
      ].join(" ")}
    >
      {liked ? "❤️" : "🤍"} {likes}
    </button>
  );
}
