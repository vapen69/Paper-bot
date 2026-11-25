# Direction visuelle du tableau de bord (règles studio-motion)

- Monde : une salle de marché la nuit. Encre vert-pétrole teintée (#081110), jamais de gris plats ni de noir pur.
- Un seul accent, le bleu glacier #7cc4ff, qui veut dire « ton bot » : courbe du bot, barres de probabilité, radar, chronos proches.
- Vert et rouge réservés au gain et à la perte. Sable #c9b48a pour la référence « garder du BTC ». Orange et bleu-violet seulement pour les logos BTC et ETH.
- Typo : Instrument Sans pour le texte, Martian Mono pour les grands chiffres, JetBrains Mono pour les petits chiffres.
- Mouvement : easings des tokens (out .16,1,.3,1 pour les arrivées, smooth .65,0,.35,1 pour les fondus, ui .4,0,.2,1 pour l'interface). Pas de rebonds. Entrées décalées par hash (pas de jumeaux).
- Effets à double tranchant, avec leur raison :
  - lueur de fond : une seule source douce, sa couleur dit si on gagne ou perd ;
  - point qui pulse : seulement sur ce qui est vraiment en direct ;
  - radar : il tourne seulement quand le bot scanne vraiment ;
  - retirés : halos sur les chiffres, reflet animé des barres, dégradé violet, rebonds, trames de fond.
- Ce qui vient de bouger prend la couleur de son sens puis revient au neutre en 0,5 s.
- Contrôle avant chaque mise en ligne : rendu 400 px et 1100 px avec les vraies données, aucun défilement horizontal, aucun recouvrement entre blocs, aucun débordement dans les cartes.
