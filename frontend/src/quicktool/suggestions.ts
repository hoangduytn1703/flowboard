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

// Real, lived-in places a buyer would film in (7/11: the studio ones made the clips look like an ad shoot).
export const BACKDROPS: Record<string, Suggestion[]> = {
  fashion: [
    { label: "Phòng ngủ có gương lớn, nắng chiều", value: "a lived-in Vietnamese apartment bedroom with a full-length mirror, a clothes rack and afternoon window light" },
    { label: "Thang máy chung cư, soi gương", value: "an apartment building elevator with a mirror wall and overhead light" },
    { label: "Phố đông xe máy, nắng trưa", value: "a busy Vietnamese street with parked motorbikes in harsh midday sun" },
    { label: "Quán cà phê sân thượng, ghế mây", value: "a sunlit Vietnamese café terrace with rattan chairs and green plants" },
    { label: "Văn phòng, góc bàn làm việc", value: "a real office corner with a desk, a laptop and window light" },
    { label: "Công viên, đường chạy bộ chiều", value: "a city park path with trees and late-afternoon sunlight" },
    { label: "Công trường / ngoài trời nắng gắt", value: "an outdoor worksite in hard afternoon sun with dust and building materials" },
  ],
  cosmetics: [
    { label: "Bồn rửa mặt nhà tắm, nắng sớm", value: "a small real bathroom with a mirror, a sink counter with a few everyday toiletries and soft morning window light" },
    { label: "Bàn trang điểm phòng ngủ, đèn bàn", value: "a bedroom dressing table with a round mirror, some makeup scattered and a warm desk lamp" },
    { label: "Ngồi trên giường, buổi tối", value: "a bed with rumpled sheets at night, lit by a warm bedside lamp" },
    { label: "Ban công rèm voan, chậu cây", value: "a sunny balcony with sheer curtains and potted plants" },
    { label: "Trong xe hơi, nắng qua kính", value: "the front seat of a car with sunlight through the windshield" },
  ],
  food: [
    { label: "Quán ăn Việt, bàn gỗ cũ", value: "a small Vietnamese eatery table with a worn wooden top, a cup of iced tea and warm afternoon light" },
    { label: "Quán vỉa hè, ghế nhựa, chiều tối", value: "a Vietnamese street-food stall with plastic stools at dusk under string lights" },
    { label: "Bàn làm việc giờ nghỉ trưa", value: "an office desk at lunch break with a laptop pushed aside" },
    { label: "Sofa phòng khách, xem phim", value: "a living-room sofa with a TV glow in the evening" },
    { label: "Bếp nhà, đèn treo", value: "a real home kitchen counter with warm pendant light" },
    { label: "Trong xe hơi, đồ ăn mang đi", value: "the front seat of a parked car with a takeaway bag" },
  ],
  grocery: [
    { label: "Bàn làm việc ở nhà, cạnh cửa sổ", value: "a real home desk by a window with a phone, a charger cable, a notebook and a coffee mug" },
    { label: "Kệ bếp, lọ gia vị", value: "a kitchen shelf with glass jars, a little cluttered, warm light" },
    { label: "Trong túi xách, đồ dùng hằng ngày", value: "an open handbag on a table with everyday items around it" },
    { label: "Ghế lái xe máy / xe hơi", value: "a motorbike seat parked on a sunny street" },
    { label: "Góc phòng khách, sofa", value: "a lived-in living-room corner with a sofa and natural light" },
  ],
  home: [
    { label: "Bếp nhà hơi bừa, nắng sáng", value: "a real Vietnamese home kitchen with a slightly busy counter, a dish rack and morning light from the window" },
    { label: "Phòng khách, sofa, đồ chơi trẻ con", value: "a lived-in living room with a sofa and a few kids' toys on the floor" },
    { label: "Góc giặt đồ, máy giặt", value: "a laundry corner with a washing machine, a basket of clothes and shelves" },
    { label: "Phòng ngủ, đèn ngủ", value: "a bedroom with warm bedside light and rumpled linen sheets" },
    { label: "Ban công nhỏ, cây xanh", value: "a small apartment balcony with green plants and morning sun" },
  ],
  other: [
    { label: "Bàn làm việc ở nhà, cạnh cửa sổ", value: "a real home desk by a window with a few everyday things, a box cutter and a cardboard shipping box" },
    { label: "Phòng khách đời thường", value: "a lived-in Vietnamese living room with a sofa, a small table and natural window light" },
    { label: "Bàn cà phê ngoài trời", value: "an outdoor café table with green plants behind" },
    { label: "Trong xe hơi", value: "the front seat of a car with daylight through the windows" },
    { label: "Phố, nắng trưa", value: "a Vietnamese street in midday sun with motorbikes passing" },
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
