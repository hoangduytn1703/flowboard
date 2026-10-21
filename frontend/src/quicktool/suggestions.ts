/**
 * Ready-made backdrops ("Bối cảnh") for the New-clip dialog. Labels are
 * Vietnamese for the user; values are English because they go straight into
 * the image prompts. Each list is keyed by template category (see
 * agent/flowboard/templates/*.json, `category`); "any" shows every group.
 *
 * The first backdrop of a category should stay equal to that category's
 * template default, so the default reads as a chosen option.
 */
export interface Suggestion {
  label: string;
  value: string;
}

export interface SuggestionGroup {
  title: string;
  items: Suggestion[];
}

export const CATEGORY_LABEL: Record<string, string> = {
  fashion: "Thời trang",
  cosmetics: "Mỹ phẩm",
  food: "Đồ ăn / uống",
  grocery: "Tạp hoá & phụ kiện",
  home: "Gia dụng",
  other: "Khác",
};

export const BACKDROPS: Record<string, Suggestion[]> = {
  fashion: [
    { label: "Studio sáng, tủ gỗ phía sau", value: "a bright minimalist studio with wooden wardrobes behind the model" },
    { label: "Quán cà phê sân thượng, ghế mây", value: "a sunlit Vietnamese café terrace with rattan chairs and green plants" },
    { label: "Phố cổ Hà Nội, tường vàng, nắng sớm", value: "a quiet Hanoi old-quarter street with yellow walls in soft morning light" },
    { label: "Phòng ngủ, gương soi toàn thân", value: "a cozy bedroom corner with a full-length mirror and warm lamp light" },
    { label: "Văn phòng co-working, cửa kính lớn", value: "a modern co-working space with large windows and white desks" },
    { label: "Công viên cây xanh, nắng chiều", value: "a green city park path with soft late-afternoon sunlight" },
    { label: "Bãi biển chiều, gió nhẹ", value: "a calm beach at golden hour with a gentle breeze" },
  ],
  cosmetics: [
    { label: "Studio pastel, ánh sáng dịu", value: "a clean pastel beauty studio with soft diffused light" },
    { label: "Bàn trang điểm phòng ngủ, gương tròn", value: "a cozy bedroom dressing table with warm lamp light and a round mirror" },
    { label: "Bồn rửa mặt đá trắng, nắng cửa sổ", value: "a bright bathroom vanity with white marble and morning window light" },
    { label: "Ban công rèm voan, chậu cây", value: "a sunny balcony with sheer curtains and potted plants" },
    { label: "Nền kem tối giản, bình hoa khô", value: "a minimalist cream-colored studio with a single dried-flower vase" },
  ],
  food: [
    { label: "Quán ăn nhanh hiện đại, bàn gỗ", value: "a bright modern fast-food diner with a wooden table" },
    { label: "Quán ăn Việt ấm cúng, bàn gỗ", value: "a cozy Vietnamese eatery table with a wooden top and warm light" },
    { label: "Bếp nhà ấm áp, đèn treo", value: "a cozy home kitchen counter with warm pendant light" },
    { label: "Xe đồ ăn đường phố, ghế nhựa, chiều tối", value: "a lively Vietnamese street-food stall with plastic stools at dusk" },
    { label: "Sân thượng, view thành phố", value: "a sunny rooftop terrace table with the city skyline behind" },
    { label: "Bàn picnic trắng trong công viên", value: "a clean white picnic table in a green park" },
  ],
  grocery: [
    { label: "Bàn trắng, điện thoại và sổ tay", value: "a clean white desk with a phone, a notebook and soft daylight" },
    { label: "Kệ bếp gọn gàng, lọ gia vị", value: "a tidy kitchen shelf with glass jars and warm light" },
    { label: "Bàn làm việc gỗ cạnh cửa sổ", value: "a tidy wooden desk by a window with soft daylight" },
    { label: "Góc phòng khách, sofa xám", value: "a modern living-room corner with a grey sofa and natural light" },
    { label: "Trong túi xách, đồ dùng hằng ngày", value: "an open handbag on a light table with everyday items around it" },
  ],
  home: [
    { label: "Bếp hiện đại, tủ trắng", value: "a bright modern Vietnamese home kitchen with white cabinets" },
    { label: "Phòng khách, sofa xám", value: "a modern living room with a grey sofa and a wooden coffee table" },
    { label: "Phòng giặt sáng sủa", value: "a clean bright laundry corner with a washing machine and shelves" },
    { label: "Phòng ngủ ấm, đèn ngủ", value: "a calm bedroom with warm bedside light and linen sheets" },
    { label: "Ban công nhỏ, cây xanh", value: "a small apartment balcony with green plants and morning sun" },
  ],
  other: [
    { label: "Bàn gỗ cạnh cửa sổ, nắng dịu", value: "a tidy wooden desk by a window with soft daylight" },
    { label: "Phòng khách sáng, đời thường", value: "a bright everyday Vietnamese living room with natural light" },
    { label: "Studio trắng, đèn ring", value: "a bright white studio desk with a ring light visible" },
    { label: "Bàn làm việc, màn hình, kệ gỗ tối", value: "a minimalist workspace with a monitor and dark wooden shelves" },
    { label: "Bàn cà phê ngoài trời", value: "an outdoor café table with blurred green plants behind" },
  ],
};

function groupsFor(source: Record<string, Suggestion[]>, category: string | undefined): SuggestionGroup[] {
  if (category && category !== "any" && source[category]) {
    return [{ title: `Hợp ${CATEGORY_LABEL[category] ?? category}`, items: source[category] }];
  }
  return Object.entries(source).map(([cat, items]) => ({ title: CATEGORY_LABEL[cat] ?? cat, items }));
}

/** Backdrops for a template category; a category-less template sees them all. */
export function backdropGroups(category: string | undefined): SuggestionGroup[] {
  return groupsFor(BACKDROPS, category);
}

/** The Vietnamese label of a known value, so the field can say what was picked. */
export function labelOf(value: string): string | null {
  for (const list of Object.values(BACKDROPS)) {
    const hit = list.find((s) => s.value === value);
    if (hit) return hit.label;
  }
  return null;
}
