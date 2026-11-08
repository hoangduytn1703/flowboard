import { useState, type ReactNode } from "react";
import { UpgradeDialog } from "../components/UpgradeDialog";
import { useFeature, type FeatureKey } from "../lib/features";
import { useAccountStore } from "../store/account";
import { PageEmpty } from "./PageState";

/** A page the account's plan does not include: say so (and which plan), with "⬆ Nâng cấp gói". */
export function FeatureGate({ feature, title, children }: { feature: FeatureKey; title: string; children: ReactNode }) {
  const allowed = useFeature(feature);
  const plan = useAccountStore((s) => s.me?.plan?.name);
  const [upgrading, setUpgrading] = useState(false);
  if (allowed) return <>{children}</>;
  return (
    <>
      <header className="qt-header"><span className="qt-header__crumb">{title}</span></header>
      <PageEmpty icon="🔒" title={`${title} chưa có trong gói ${plan ?? "của bạn"}`}
                 actions={<button type="button" className="qt-btn qt-btn--accent" onClick={() => setUpgrading(true)}>⬆ Nâng cấp gói</button>}>
        Nâng cấp lên gói có tính năng này, hoặc liên hệ người quản lý DFlow. Các phần khác (clip, sản phẩm, người mẫu, prompt) vẫn dùng bình thường.
      </PageEmpty>
      {upgrading && <UpgradeDialog onClose={() => setUpgrading(false)} />}
    </>
  );
}
