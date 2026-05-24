const ARCANA_DETAILS = {
    1: { name: "Маг", emoji: "✨", key: "Воля, мастерство, начало", plus: "Инициативность, уверенность, умение начинать новое, лидерство.", minus: "Манипуляции, поверхностность, эгоизм, неумение доводить до конца.", practices: "Каждый день делай одно дело, которое давно откладывал." },
    2: { name: "Верховная Жрица", emoji: "📿", key: "Интуиция, тайна, подсознание", plus: "Глубокая интуиция, дипломатичность, понимание скрытых процессов.", minus: "Сплетни, двойственность, скрытность, пассивная агрессия.", practices: "Введи практику утренней тишины без гаджетов на 15 минут." },
    3: { name: "Императрица", emoji: "👑", key: "Изобилие, природа, творчество", plus: "Плодородие, забота, материальное благополучие, созидание.", minus: "Контроль, гиперопека, зацепка за материальное, гордыня.", practices: "Займись творчеством или уходом за растениями без фонового спеха." },
    4: { name: "Император", emoji: "🏛️", key: "Структура, власть, порядок", plus: "Организованность, авторитет, защита, стратегическое мышление.", minus: "Деспотизм, жесткость, неумение уступать, хаос в делах.", practices: "Составь четкий письменный план на неделю и следуй ему." },
    5: { name: "Иерофант", emoji: "📖", key: "Учение, традиция, наставничество", plus: "Мудрость, системные знания, следование правилам, дар учителя.", minus: "Поучительство, догматизм, нежелание учиться новому.", practices: "Поделись своими знаниями с тем, кто в них искренне нуждается." },
    6: { name: "Влюблённые", emoji: "💕", key: "Выбор, гармония, партнёрство", plus: "Сердечность, умение делать выбор по сердцу, коммуникабельность.", minus: "Идеализация, нерешительность, зависимость от чужого мнения.", practices: "Принимая решение, спроси себя: «Я делаю это из любви или из страха?»" },
    7: { name: "Колесница", emoji: "🚀", key: "Прорыв, победа, решимость", plus: "Целеустремленность, лидерство, управление движением, триумф.", minus: "Агрессия, воинственность, лень, движение по головам.", practices: "Поставь одну измеримую цель на месяц и зафиксируй первые шаги." },
    8: { name: "Сила", emoji: "🦁", key: "Внутренняя сила, смелость", plus: "Принятие своей животной природы, выносливость, великодушие.", minus: "Давление, вспышки ярости, бессилие, злоупотребление силой.", practices: "Направь избыток энергии в интенсивную физическую нагрузку." },
    9: { name: "Отшельник", emoji: "🏔️", key: "Мудрость, уединение, поиск", plus: "Глубина, самодостаточность, аналитический склад ума, зрелость.", minus: "Изоляция, уход в себя, гордыня, страх одиночества.", practices: "Выдели один вечер для уединенного чтения или прогулки без телефона." },
    10: { name: "Колесо Фортуны", emoji: "🎡", key: "Судьба, циклы, перемены", plus: "Умение ловить поток, удачливость, легкое отношение к жизни.", minus: "Пассивность, фатализм, сопротивление переменам, застой.", practices: "Запиши 3 неожиданных благоприятных совпадения за неделю." },
    11: { name: "Справедливость", emoji: "⚖️", key: "Карма, баланс, истина", plus: "Объективность, честность, понимание причинно-следственных связей.", minus: "Осуждение, борьба за правду, поиск виноватых, обиды.", practices: "В конфликтной ситуации посмотри на нее с позиции наблюдателя." },
    12: { name: "Повешенный", emoji: "🔄", key: "Пауза, переосмысление, жертва", plus: "Новый взгляд на вещи, креативность, бескорыстное служение.", minus: "Жертвенность, обидчивость, иллюзии, зависание в проблемах.", practices: "Попробуй найти нестандартное творческое решение привычной задаче." },
    13: { name: "Смерть", emoji: "💀", key: "Трансформация, обновление", plus: "Способность легко отпускать старое, решительность, кризис-менеджмент.", minus: "Страх перемен, зацепка за прошлое, внутренняя стагнация.", practices: "Проведи ревизию и выброси из дома 10 ненужных вещей." },
    14: { name: "Умеренность", emoji: "🌊", key: "Баланс, гармония, равновесие", plus: "Чувство меры, терпение, целительские способности, спокойствие.", minus: "Дисбаланс, крайности, несдержанность, внутренняя суета.", practices: "Соблюдай баланс в питании и потреблении контента в течение дня." },
    15: { name: "Дьявол", emoji: "⛓️", key: "Тень, зависимость, искушение", plus: "Харизма, видение человеческой сути, материальный успех, магнетизм.", minus: "Зависимости, манипуляции, жажда власти, сильная ревность.", practices: "Честно признай и выпиши свои теневые желания на листок." },
    16: { name: "Башня", emoji: "🗼", key: "Разрушение, прозрение, освобождение", plus: "Духовная перестройка, выход из иллюзий, сила духа в кризисах.", minus: "Агрессия, страх разрушения, хаос, жесткое эго.", practices: "Начни менять старые жесткие привычки, начиная с малых мелочей." },
    17: { name: "Звезда", emoji: "⭐", key: "Надежда, вдохновение, вера", plus: "Яркость, проявление талантов, мечтательность, оптимизм.", minus: "Звездная болезнь, серость, неверие в себя, оторванность от реальности.", practices: "Сделай конкретный шаг к проявлению своего таланта на публике." },
    18: { name: "Луна", emoji: "🌙", key: "Иллюзии, подсознание, страхи", plus: "Развитое воображение, материализация мыслей, глубокая эмпатия.", minus: "Страхи, фобии, обманы, уход в вымышленный мир.", practices: "Выписывай свои страхи на бумагу методом фрирайтинга." },
    19: { name: "Солнце", emoji: "☀️", key: "Радость, успех, витальность", plus: "Щедрость, лидерство, внутренний ребенок, масштабные проекты.", minus: "Эгоцентризм, самосожжение, агрессия, гордыня.", practices: "Направь свое внимание на то, что приносит искреннюю радость." },
    20: { name: "Суд", emoji: "📯", key: "Пробуждение, призвание, переоценка", plus: "Родовая поддержка, глобальные изменения, системное мышление.", minus: "Осуждение родственников, застревание в родовых обидах.", practices: "Поблагодари родителей или мысленно поклонись своему роду." },
    21: { name: "Мир", emoji: "🌍", key: "Завершение, целостность, реализация", plus: "Космополитизм, глобальное восприятие, миролюбие, свобода от рамок.", minus: "Враждебность к миру, ограничение себя, узкое мышление.", practices: "Изучи что-то новое о культуре или традициях другой страны." },
    22: { name: "Шут", emoji: "🎭", key: "Свобода, новое начало, спонтанность", plus: "Легкость, доверие вселенной, открытость новому, отсутствие рамок.", minus: "Безответственность, глупость, хаос, внутренняя несвобода.", practices: "Сделай сегодня что-то спонтанное, чего никогда не делал ранее." }
};

document.addEventListener("DOMContentLoaded", () => {
    const data = window.MATRIX_DATA;
    if (!data) return;

    document.getElementById("cover-user-name").textContent = data.user_name;
    document.getElementById("cover-archetype-name").textContent = data.archetype_name;
    document.getElementById("cover-arcana-meta").textContent = `${data.archetype_number} аркан`;
    document.getElementById("cover-date").textContent = `Дата генерации: ${data.generated_at}`;
    document.getElementById("footer-url").textContent = data.report_base_url;

    const allPositions = [
        "center", "top", "bottom", "left", "right",
        "talent_zone", "comfort_zone", "portrait_zone",
        "inner_f", "inner_g", "inner_h", "inner_i"
    ];

    allPositions.forEach(pos => {
        const node = document.querySelector(`.matrix-node[data-position="${pos}"]`);
        if (node) {
            const val = data[pos];
            const name = data.arcana_names[pos] || ARCANA_DETAILS[val]?.name || "";
            node.innerHTML = `<span class="node-number">${val}</span><span class="node-label">${name}</span>`;
            node.addEventListener("click", () => openModal(val));
        }
    });

    document.getElementById("sky-line-text").textContent = data.sky_line.join(" → ");
    document.getElementById("earth-line-text").textContent = data.earth_line.join(" → ");
    document.getElementById("relationship-line-text").textContent = data.relationship_line.join(" → ");
    document.getElementById("money-line-text").textContent = data.money_line.join(" → ");

    const miniChain = document.getElementById("karmic-mini-chain");
    data.karmic_tail.forEach((val, idx) => {
        const circle = document.createElement("div");
        circle.className = "mini-chain-circle";
        circle.textContent = val;
        circle.addEventListener("click", () => openModal(val));
        miniChain.appendChild(circle);
        if (idx < data.karmic_tail.length - 1) {
            const arrow = document.createElement("span");
            arrow.className = "mini-chain-arrow";
            arrow.textContent = "→";
            miniChain.appendChild(arrow);
        }
    });

    document.getElementById("rel-point-val").textContent = data.relationship_point;
    document.getElementById("parent-lines-val").textContent = `${data.inner_g} / ${data.inner_i}`;

    const collectedNumbers = [
        data.center, data.top, data.bottom, data.left, data.right,
        data.talent_zone, data.comfort_zone, data.portrait_zone,
        data.inner_f, data.inner_g, data.inner_h, data.inner_i,
        ...data.sky_line, ...data.earth_line, ...data.relationship_line, ...data.money_line,
        ...data.karmic_tail, data.relationship_point
    ];

    const freqMap = {};
    collectedNumbers.forEach(n => freqMap[n] = (freqMap[n] || 0) + 1);

    const sortedFreq = Object.entries(freqMap)
        .map(([num, count]) => ({ num: parseInt(num), count }))
        .filter(item => item.count >= 2)
        .sort((a, b) => b.count - a.count)
        .slice(0, 5);

    const coreContainer = document.getElementById("core-energies-container");
    if (sortedFreq.length > 0) {
        sortedFreq.forEach(item => {
            const card = document.createElement("div");
            card.className = "core-card";
            const name = ARCANA_DETAILS[item.num]?.name || "Аркан";
            card.innerHTML = `
                <div class="core-num">${item.num}</div>
                <span class="core-name">${name}</span>
                <span class="core-count">${item.count} совпадений</span>
            `;
            card.addEventListener("click", () => openModal(item.num));
            coreContainer.appendChild(card);
        });
    } else {
        document.getElementById("matrix-core-section").style.display = "none";
    }

    document.getElementById("dash-center-num").textContent = data.center;
    document.getElementById("dash-center-name").textContent = data.arcana_names.center || "";
    document.getElementById("dash-talent-num").textContent = data.talent_zone;
    document.getElementById("dash-talent-name").textContent = data.arcana_names.talent_zone || "";
    document.getElementById("dash-karmic1-num").textContent = data.karmic_tail[0];
    document.getElementById("dash-karmic1-name").textContent = ARCANA_DETAILS[data.karmic_tail[0]]?.name || "";
    document.getElementById("dash-karmic2-num").textContent = data.karmic_tail[1];
    document.getElementById("dash-karmic2-name").textContent = ARCANA_DETAILS[data.karmic_tail[1]]?.name || "";
    document.getElementById("dash-comfort-num").textContent = data.comfort_zone;
    document.getElementById("dash-comfort-name").textContent = data.arcana_names.comfort_zone || "";

    document.querySelectorAll(".dash-card").forEach(card => {
        card.addEventListener("click", () => {
            const id = card.getAttribute("data-target");
            document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
        });
    });

    document.getElementById("analysis-main-archetype").textContent = data.analysis.main_archetype;
    document.getElementById("analysis-karmic-tail").textContent = data.analysis.karmic_tail_analysis;

    const fullKarmic = document.getElementById("full-karmic-chain");
    const karmicLabels = ["Причина", "Следствие", "Урок"];
    const karmicBorders = ["circle-gold", "circle-orange", "circle-green"];
    data.karmic_tail.forEach((val, idx) => {
        const node = document.createElement("div");
        node.className = "karmic-node";
        node.innerHTML = `
            <div class="karmic-circle ${karmicBorders[idx]}">${val}</div>
            <span>${karmicLabels[idx]}</span>
        `;
        node.querySelector(".karmic-circle").addEventListener("click", () => openModal(val));
        fullKarmic.appendChild(node);
        if (idx < 2) {
            const arrow = document.createElement("div");
            arrow.className = "karmic-arrow";
            arrow.textContent = "→";
            fullKarmic.appendChild(arrow);
        }
    });

    const twinPairs = [[1, 7], [2, 6], [3, 5], [4, 4]];
    const twinsContainer = document.getElementById("twins-container");
    let hasTwins = false;

    twinPairs.forEach(([p1, p2]) => {
        const hasP1 = collectedNumbers.includes(p1);
        const hasP2 = collectedNumbers.includes(p2);
        
        if (hasP1 && hasP2) {
            hasTwins = true;
            const card = document.createElement("div");
            card.className = "twin-card";
            const a1 = ARCANA_DETAILS[p1];
            const a2 = ARCANA_DETAILS[p2];
            
            card.innerHTML = `
                <div class="twin-header">
                    <div class="twin-pair">${p1} + ${p2} = 8</div>
                    <div class="twin-names">${a1.emoji} ${a1.name} и ${a2.emoji} ${a2.name}</div>
                </div>
                <div class="twin-conflict">Энергии этих арканов могут вести внутренний диалог, требуя баланса между действием и структурой.</div>
                <div class="twin-advice">Попробуй объединить их потенциал, не уходя в крайности одного из проявлений.</div>
            `;
            twinsContainer.appendChild(card);
        }
    });

    if (!hasTwins) {
        document.getElementById("matrix-twins-section").style.display = "none";
    }

    const emptyContainer = document.getElementById("empty-cells-container");
    let hasEmpty = false;
    for (let i = 1; i <= 22; i++) {
        if (!collectedNumbers.includes(i)) {
            hasEmpty = true;
            const item = document.createElement("div");
            item.className = "empty-cell-item";
            item.innerHTML = `
                <div class="empty-circle">${i}</div>
                <div class="empty-name">${ARCANA_DETAILS[i]?.name || ""}</div>
            `;
            item.addEventListener("click", () => openModal(i));
            emptyContainer.appendChild(item);
        }
    }
    if (!hasEmpty) {
        document.getElementById("matrix-empty-section").style.display = "none";
    }

    const chakraLayout = [
        { key: "sahasrara", name: "Сахасрара (Макушка)", desc: "Духовный канал, связь с Высшим" },
        { key: "ajna", name: "Аджна (Голова)", desc: "Мышление, интуиция, видение" },
        { key: "vishudha", name: "Вишудха (Горло)", desc: "Самовыражение, творчество" },
        { key: "anahata", name: "Анахата (Сердце)", desc: "Чувства, принятие, любовь" },
        { key: "manipura", name: "Манипура (Живот)", desc: "Воля, деньги, социум" },
        { key: "svadhisthana", name: "Свадхистана (Низ живота)", desc: "Удовольствия, отношения" },
        { key: "muladhara", name: "Муладхара (Корень)", desc: "Опора, безопасность, род" },
        { key: "organism", name: "Организм (итог)", desc: "Суммарный показатель всех центров" }
    ];

    const chakrasContainer = document.getElementById("chakras-container");
    chakraLayout.forEach(ch => {
        const card = document.createElement("div");
        card.className = "chakra-card";
        if (ch.key === "organism") card.classList.add("organism-card");

        const sky = data.chakra_data[`${ch.key}_sky`];
        const earth = data.chakra_data[`${ch.key}_earth`];
        const k = data.chakra_data[`${ch.key}_key`];

        card.innerHTML = `
            <div class="chakra-header">
                <span class="chakra-title">${ch.name}</span>
                <span class="chakra-loc">${ch.key === "organism" ? "Общий ресурс" : "Локация"}</span>
            </div>
            <p class="chakra-desc">${ch.desc}</p>
            <div class="chakra-values">
                <div class="val-block">
                    <span class="val-label">Небо</span>
                    <span class="val-num clickable-num">${sky}</span>
                </div>
                <div class="val-block">
                    <span class="val-label">Земля</span>
                    <span class="val-num clickable-num">${earth}</span>
                </div>
                <div class="val-block">
                    <span class="val-label">Ключ</span>
                    <span class="val-num accent-orange clickable-num">${k}</span>
                </div>
            </div>
        `;
        card.querySelectorAll(".clickable-num").forEach(numEl => {
            numEl.addEventListener("click", () => openModal(parseInt(numEl.textContent)));
        });
        chakrasContainer.appendChild(card);
    });

    const purposesContainer = document.getElementById("purposes-container");
    const pData = [
        { title: "Личное предназначение ☀", cls: "title-orange", text: data.analysis.life_purpose, energies: `Энергии: Небо (${data.sky_line[0]}) + Земля (${data.earth_line[0]})` },
        { title: "Родовое предназначение 🌳", cls: "title-green", text: data.analysis.ancestral_programs, energies: `Энергии: Мать (${data.inner_i}) + Отец (${data.inner_g})` },
        { title: "Духовное предназначение ✦", cls: "title-gold", text: data.analysis.life_forecast, energies: `Энергии: Духовный путь (${data.sky_line[1]})` },
        { title: "Высшее духовное ◈", cls: "title-orange", text: data.analysis.karmic_tail_analysis, energies: `Энергии: Высшее (${data.earth_line[1]})` }
    ];

    pData.forEach(p => {
        const card = document.createElement("div");
        card.className = "purpose-card";
        card.innerHTML = `
            <div class="purpose-title ${p.cls}">${p.title}</div>
            <p class="purpose-text">${p.text}</p>
            <div class="purpose-energies">${p.energies}</div>
        `;
        purposesContainer.appendChild(card);
    });

    document.getElementById("analysis-ancestral-programs").textContent = data.analysis.ancestral_programs;
    document.getElementById("analysis-strengths").textContent = data.analysis.strengths;
    document.getElementById("analysis-shadow-side").textContent = data.analysis.shadow_side;
    document.getElementById("analysis-relationship-dynamics").textContent = data.analysis.relationship_dynamics;
    document.getElementById("analysis-financial-scenario").textContent = data.analysis.financial_scenario;

    const buildLineComponent = (containerId, emoji, name, lineData) => {
        const cont = document.getElementById(containerId);
        cont.innerHTML = `
            <div class="line-info">
                <span class="line-emoji">${emoji}</span>
                <span class="line-title">${name}</span>
            </div>
            <div class="line-pipe"></div>
        `;
        const pipe = cont.querySelector(".line-pipe");
        lineData.forEach((val, idx) => {
            const circ = document.createElement("div");
            circ.className = "pipe-circle";
            circ.textContent = val;
            circ.addEventListener("click", () => openModal(val));
            pipe.appendChild(circ);
            if (idx < lineData.length - 1) {
                const conn = document.createElement("div");
                conn.className = "pipe-connect";
                pipe.appendChild(conn);
            }
        });
    };

    buildLineComponent("rel-line-component", "💞", "Линия отношений", data.relationship_line);
    buildLineComponent("money-line-component", "💼", "Линия денег", data.money_line);

    document.getElementById("analysis-life-forecast").textContent = data.analysis.life_forecast;

    const timeline = document.getElementById("lifecycle-timeline");
    const periods = Object.entries(data.life_periods);
    periods.forEach(([ageKey, arcanaVal], idx) => {
        const age = ageKey.replace("age_", "") + " лет";
        const node = document.createElement("div");
        node.className = "timeline-node";
        node.innerHTML = `
            <div class="timeline-circle">${arcanaVal}</div>
            <span class="timeline-age">${age}</span>
        `;
        node.querySelector(".timeline-circle").addEventListener("click", () => openModal(arcanaVal));
        timeline.appendChild(node);

        if (idx < periods.length - 1) {
            const conn = document.createElement("div");
            conn.className = "timeline-connector";
            timeline.appendChild(conn);
        }
    });

    document.getElementById("current-year-val").textContent = `${data.current_year_arcana} аркан`;

    const nextYearsStack = document.getElementById("next-years-stack");
    const curYearNum = parseInt(data.generated_at.split(".")[2]) || 2026;
    for (let i = 0; i < 3; i++) {
        const targetYear = curYearNum + i;
        const yearArcana = (data.current_year_arcana + i) % 22 || 22;
        const arcInfo = ARCANA_DETAILS[yearArcana];
        const miniCard = document.createElement("div");
        miniCard.className = "forecast-mini-card";
        miniCard.innerHTML = `
            <div class="forecast-mini-head">${targetYear} год — ${yearArcana} ${arcInfo?.name} ${arcInfo?.emoji}</div>
            <div class="forecast-mini-text">Время раскрытия потенциала в векторе энергии баланса и внутренней структуры. Попробуй сонаправиться с текущим циклом.</div>
        `;
        nextYearsStack.appendChild(miniCard);
    }

    const keyAgesStack = document.getElementById("key-ages-stack");
    const keyAges = [17, 25, 33, 40, 50];
    keyAges.forEach(age => {
        const val = data.life_periods[`age_${age}`] || 7;
        const arcInfo = ARCANA_DETAILS[val];
        const miniCard = document.createElement("div");
        miniCard.className = "forecast-mini-card";
        miniCard.innerHTML = `
            <div class="forecast-mini-head">Возраст ${age} лет — ${val} ${arcInfo?.name}</div>
            <div class="forecast-mini-text">Важная точка переосмысления. Потенциал энергии указывает на необходимость заложить новый фундамент развития.</div>
        `;
        keyAgesStack.appendChild(miniCard);
    });

    document.getElementById("analysis-recurring-mistakes").textContent = data.analysis.recurring_mistakes;
    document.getElementById("analysis-internal-conflicts").textContent = data.analysis.internal_conflicts;

    const recContainer = document.getElementById("recommendations-container");
    const parsedLines = data.analysis.ai_recommendations.split("\n").filter(l => l.trim());
    
    parsedLines.forEach((line, i) => {
        const lower = line.toLowerCase();
        let category = "Практика";
        if (/тело|физическ|йог|дыхание|спорт|сон|движение|тренировк|прогулк/.test(lower)) category = "Тело";
        else if (/ум|мысл|анализ|изучени|чтение|план|интеллект|обучени|запис/.test(lower)) category = "Ум";
        else if (/дух|медитаци|осознанност|тишина|благодарност|духовн|молитв/.test(lower)) category = "Дух";

        const cleanText = line.replace(/^\d+\.\s*/, "");
        const dayNum = i + 1;
        const storageKey = `nura_day_check_${dayNum}`;

        const item = document.createElement("div");
        item.className = "rec-day";
        item.innerHTML = `
            <div class="rec-checkbox-wrap">
                <input type="checkbox" id="chk-day-${dayNum}">
                <label for="chk-day-${dayNum}" class="custom-checkmark"></label>
            </div>
            <div class="rec-main">
                <div class="rec-head">
                    <span class="rec-day-num">День ${dayNum}</span>
                    <span class="rec-cat">${category}</span>
                </div>
                <p class="rec-text">${cleanText}</p>
            </div>
        `;

        const chk = item.querySelector('input[type="checkbox"]');
        if (localStorage.getItem(storageKey) === "true") {
            chk.checked = true;
        }

        chk.addEventListener("change", () => {
            localStorage.setItem(storageKey, chk.checked);
        });

        recContainer.appendChild(item);
    });

    const practicesContainer = document.getElementById("practices-container");
    const practiceLayoutData = [
        { zone: "Развивающее упражнение (Зона талантов)", num: data.talent_zone },
        { zone: "Восстанавливающее упражнение (Зона комфорта)", num: data.comfort_zone },
        { zone: "Трансформирующее упражнение (Кармический хвост)", num: data.karmic_tail[2] }
    ];

    practiceLayoutData.forEach(p => {
        const info = ARCANA_DETAILS[p.num];
        if (info) {
            const card = document.createElement("div");
            card.className = "practice-card";
            card.innerHTML = `
                <div class="practice-head">
                    <div class="practice-title">${info.emoji} Практика аркана ${info.name}</div>
                    <div class="practice-frequency">3 раза в неделю</div>
                </div>
                <div class="practice-steps">Направление: ${p.zone}.\n${info.practices} Попробуй выполнять это осознанно, фиксируя внутренние изменения.</div>
            `;
            practicesContainer.appendChild(card);
        }
    });

    const modal = document.getElementById("arcana-modal");
    const openModal = (num) => {
        const details = ARCANA_DETAILS[num];
        if (!details) return;

        document.getElementById("modal-title").textContent = `${details.emoji} ${num}. ${details.name}`;
        document.getElementById("modal-key-phrase").textContent = details.key;
        document.getElementById("modal-plus-text").textContent = details.plus;
        document.getElementById("modal-minus-text").textContent = details.minus;
        document.getElementById("modal-practices-text").textContent = details.practices;

        modal.classList.add("modal-active");
    };

    const closeModal = () => {
        modal.classList.remove("modal-active");
    };

    document.getElementById("modal-close-btn").addEventListener("click", closeModal);
    document.getElementById("modal-confirm-btn").addEventListener("click", closeModal);
    modal.querySelector(".modal-overlay").addEventListener("click", closeModal);
    
    window.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && modal.classList.contains("modal-active")) {
            closeModal();
        }
    });

    const observerOptions = { threshold: 0.1 };
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add("visible");
            }
        });
    }, observerOptions);

    document.querySelectorAll(".animate-section").forEach(sec => observer.observe(sec));
});