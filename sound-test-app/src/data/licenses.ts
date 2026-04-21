/**
 * 오픈소스 라이선스 데이터
 * - 프로젝트에서 사용하는 모든 오픈소스 라이브러리의 라이선스 정보
 */

export interface LicenseGroup {
  license: string;
  packages: { name: string; version: string }[];
  text: string;
}

export const LICENSE_GROUPS: LicenseGroup[] = [
  // ── MIT ──
  {
    license: "MIT License",
    packages: [
      { name: "React", version: "19.2.4" },
      { name: "React DOM", version: "19.2.4" },
      { name: "Vite", version: "7.0.4" },
      { name: "tokio", version: "1.49.0" },
      { name: "hyper", version: "1.8.1" },
      { name: "tower", version: "0.5.3" },
      { name: "tower-http", version: "0.6.8" },
      { name: "tracing", version: "0.1.44" },
      { name: "darling", version: "0.21.3" },
      { name: "rfd", version: "0.16.0" },
      { name: "objc2", version: "0.6.3" },
      { name: "block2", version: "0.6.2" },
      { name: "gtk (Rust)", version: "0.18.2" },
      { name: "glib (Rust)", version: "0.18.5" },
      { name: "cairo-rs", version: "0.18.5" },
      { name: "pango (Rust)", version: "0.18.3" },
      { name: "webkit2gtk", version: "2.0.2" },
      { name: "soup3", version: "0.5.0" },
      { name: "webview2-com", version: "0.38.2" },
      { name: "quick-xml", version: "0.38.4" },
      { name: "plist", version: "1.8.0" },
      { name: "schemars", version: "0.8.22" },
      { name: "cargo_metadata", version: "0.19.2" },
      { name: "convert_case", version: "0.4.0" },
      { name: "derive_more", version: "0.99.20" },
      { name: "cookie", version: "0.18.1" },
      { name: "http-body", version: "1.0.1" },
      { name: "bytes", version: "1.11.1" },
      { name: "mio", version: "1.1.1" },
      { name: "slab", version: "0.4.12" },
    ],
    text: `MIT License

Copyright (c) <year> <copyright holders>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.`,
  },

  // ── Apache-2.0 ──
  {
    license: "Apache License 2.0",
    packages: [
      { name: "Tauri", version: "2.10.2" },
      { name: "@tauri-apps/api", version: "2.10.1" },
      { name: "@tauri-apps/plugin-dialog", version: "2.6.0" },
      { name: "@tauri-apps/plugin-opener", version: "2.5.3" },
      { name: "tauri-build", version: "2.5.5" },
      { name: "tauri-plugin-fs", version: "2.4.5" },
      { name: "serde", version: "1.0.228" },
      { name: "serde_json", version: "1.0.149" },
      { name: "base64", version: "0.22" },
      { name: "libc", version: "0.2.182" },
      { name: "xlsx (SheetJS)", version: "0.18.5" },
      { name: "TypeScript", version: "5.8.3" },
      { name: "tao", version: "0.34.5" },
      { name: "reqwest", version: "0.13.2" },
      { name: "chrono", version: "0.4.43" },
      { name: "regex", version: "1.12.3" },
      { name: "url", version: "2.5.8" },
      { name: "uuid", version: "1.21.0" },
      { name: "anyhow", version: "1.0.101" },
      { name: "async-trait", version: "0.1.89" },
      { name: "futures-util", version: "0.3.31" },
      { name: "crossbeam-channel", version: "0.5.15" },
      { name: "once_cell", version: "1.21.3" },
      { name: "proc-macro2", version: "1.0.106" },
      { name: "quote", version: "1.0.44" },
      { name: "syn", version: "1.0.109" },
      { name: "tempfile", version: "3.25.0" },
      { name: "toml", version: "0.8.2" },
      { name: "semver", version: "1.0.27" },
      { name: "window-vibrancy", version: "0.6.0" },
      { name: "softbuffer", version: "0.4.8" },
      { name: "muda", version: "0.17.1" },
      { name: "tray-icon", version: "0.21.3" },
      { name: "embed-resource", version: "3.0.6" },
      { name: "swift-rs", version: "1.0.7" },
    ],
    text: `Apache License
Version 2.0, January 2004
http://www.apache.org/licenses/

TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

1. Definitions.

"License" shall mean the terms and conditions for use, reproduction,
and distribution as defined by Sections 1 through 9 of this document.

"Licensor" shall mean the copyright owner or entity authorized by
the copyright owner that is granting the License.

"Legal Entity" shall mean the union of the acting entity and all
other entities that control, are controlled by, or are under common
control with that entity. For the purposes of this definition,
"control" means (i) the power, direct or indirect, to cause the
direction or management of such entity, whether by contract or
otherwise, or (ii) ownership of fifty percent (50%) or more of the
outstanding shares, or (iii) beneficial ownership of such entity.

"You" (or "Your") shall mean an individual or Legal Entity
exercising permissions granted by this License.

"Source" form shall mean the preferred form for making modifications,
including but not limited to software source code, documentation
source, and configuration files.

"Object" form shall mean any form resulting from mechanical
transformation or translation of a Source form, including but
not limited to compiled object code, generated documentation,
and conversions to other media types.

"Work" shall mean the work of authorship, whether in Source or
Object form, made available under the License, as indicated by a
copyright notice that is included in or attached to the work.

"Derivative Works" shall mean any work, whether in Source or Object
form, that is based on (or derived from) the Work and for which the
editorial revisions, annotations, elaborations, or other modifications
represent, as a whole, an original work of authorship.

"Contribution" shall mean any work of authorship, including
the original version of the Work and any modifications or additions
to that Work or Derivative Works thereof, that is intentionally
submitted to the Licensor for inclusion in the Work by the copyright owner
or by an individual or Legal Entity authorized to submit on behalf of
the copyright owner.

"Contributor" shall mean Licensor and any individual or Legal Entity
on behalf of whom a Contribution has been received by the Licensor and
subsequently incorporated within the Work.

2. Grant of Copyright License. Subject to the terms and conditions of
this License, each Contributor hereby grants to You a perpetual,
worldwide, non-exclusive, no-charge, royalty-free, irrevocable
copyright license to reproduce, prepare Derivative Works of,
publicly display, publicly perform, sublicense, and distribute the
Work and such Derivative Works in Source or Object form.

3. Grant of Patent License. Subject to the terms and conditions of
this License, each Contributor hereby grants to You a perpetual,
worldwide, non-exclusive, no-charge, royalty-free, irrevocable
(except as stated in this section) patent license to make, have made,
use, offer to sell, sell, import, and otherwise transfer the Work,
where such license applies only to those patent claims licensable
by such Contributor that are necessarily infringed by their
Contribution(s) alone or by combination of their Contribution(s)
with the Work to which such Contribution(s) was submitted.

4. Redistribution. You may reproduce and distribute copies of the
Work or Derivative Works thereof in any medium, with or without
modifications, and in Source or Object form, provided that You
meet the following conditions:

(a) You must give any other recipients of the Work or
    Derivative Works a copy of this License; and

(b) You must cause any modified files to carry prominent notices
    stating that You changed the files; and

(c) You must retain, in the Source form of any Derivative Works
    that You distribute, all copyright, patent, trademark, and
    attribution notices from the Source form of the Work,
    excluding those notices that do not pertain to any part of
    the Derivative Works; and

(d) If the Work includes a "NOTICE" text file as part of its
    distribution, then any Derivative Works that You distribute must
    include a readable copy of the attribution notices contained
    within such NOTICE file, excluding any notices that do not
    pertain to any part of the Derivative Works, in at least one
    of the following places: within a NOTICE text file distributed
    as part of the Derivative Works; within the Source form or
    documentation, if provided along with the Derivative Works; or,
    within a display generated by the Derivative Works, if and
    wherever such third-party notices normally appear.

5. Submission of Contributions.

6. Trademarks. This License does not grant permission to use the trade
names, trademarks, service marks, or product names of the Licensor.

7. Disclaimer of Warranty. Unless required by applicable law or
agreed to in writing, Licensor provides the Work (and each
Contributor provides its Contributions) on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
implied, including, without limitation, any warranties or conditions
of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
PARTICULAR PURPOSE.

8. Limitation of Liability. In no event and under no legal theory,
whether in tort (including negligence), contract, or otherwise,
unless required by applicable law (such as deliberate and grossly
negligent acts) or agreed to in writing, shall any Contributor be
liable to You for damages, including any direct, indirect, special,
incidental, or consequential damages of any character arising as a
result of this License or out of the use or inability to use the
Work (including but not limited to damages for loss of goodwill,
work stoppage, computer failure or malfunction, or any and all
other commercial damages or losses), even if such Contributor
has been advised of the possibility of such damages.

9. Accepting Warranty or Additional Liability.

END OF TERMS AND CONDITIONS`,
  },

  // ── MPL-2.0 ──
  {
    license: "Mozilla Public License 2.0",
    packages: [
      { name: "cssparser", version: "0.29.6" },
      { name: "cssparser-macros", version: "0.6.1" },
      { name: "selectors", version: "0.24.0" },
      { name: "dtoa-short", version: "0.3.5" },
      { name: "option-ext", version: "0.2.0" },
    ],
    text: `Mozilla Public License Version 2.0

1. Definitions

1.1. "Contributor" means each individual or legal entity that creates,
contributes to the creation of, or owns Covered Software.

1.2. "Contributor Version" means the combination of the Contributions
of others (if any) used by a Contributor and that particular
Contributor's Contribution.

1.3. "Contribution" means Covered Software of a particular Contributor.

1.4. "Covered Software" means Source Code Form to which the initial
Contributor has attached the notice in Exhibit A, the Executable Form
of such Source Code Form, and Modifications of such Source Code Form,
in each case including portions thereof.

1.5. "Incompatible With Secondary Licenses" means that the initial
Contributor has attached the notice described in Exhibit B to the Covered
Software.

1.6. "Executable Form" means any form of the work other than Source Code Form.

1.7. "Larger Work" means a work that combines Covered Software with
other material, in a separate file or files, that is not Covered Software.

1.8. "License" means this document.

1.9. "Licensable" means having the right to grant, to the maximum extent
possible, whether at the time of the initial grant or subsequently, any
and all of the rights conveyed by this License.

1.10. "Modifications" means any of the following:
(a) any file in Source Code Form that results from an addition to,
deletion from, or modification of the contents of Covered Software; or
(b) any new file in Source Code Form that contains any Covered Software.

1.11. "Patent Claims" of a Contributor means any patent claim(s),
including without limitation, method, process, and apparatus claims,
in any patent Licensable by such Contributor that would be infringed,
but for the grant of the License, by the making, using, selling,
offering for sale, having made, import, or transfer of either its
Contributions or its Contributor Version.

1.12. "Secondary License" means either the GNU General Public License,
Version 2.0, the GNU Lesser General Public License, Version 2.1, the
GNU Affero General Public License, Version 3.0, or any later versions
of those licenses.

1.13. "Source Code Form" means the form of the work preferred for making modifications.

2. License Grants and Conditions

2.1. Grants
Each Contributor hereby grants You a world-wide, royalty-free,
non-exclusive license:
(a) under intellectual property rights (other than patent or trademark)
Licensable by such Contributor to use, reproduce, make available,
modify, display, perform, distribute, and otherwise exploit its
Contributions, either on an unmodified basis, with Modifications, or
as part of a Larger Work; and
(b) under Patent Claims of such Contributor to make, use, sell, offer
for sale, have made, import, and otherwise transfer either its
Contributions or its Contributor Version.

2.2. Effective Date
The licenses granted in Section 2.1 with respect to any Contribution
become effective for each Contribution on the date the Contributor first
distributes such Contribution.

2.3. Limitations on Grant Scope
The licenses granted in this Section 2 are the only rights granted under
this License.

2.4. Subsequent Licenses
No Contributor makes additional grants as a result of Your choice to
distribute the Covered Software under a subsequent version of this
License (see Section 10.2) or under the terms of a Secondary License
(if permitted under the terms of Section 3.3).

2.5. Representation
Each Contributor represents that the Contributor believes its
Contributions are its original creation(s) or it has sufficient rights
to grant the rights to its Contributions conveyed by this License.

3. Responsibilities

3.1. Distribution of Source Form
All distribution of Covered Software in Source Code Form, including any
Modifications that You create or to which You contribute, must be under
the terms of this License.

3.2. Distribution of Executable Form
If You distribute Covered Software in Executable Form then such Covered
Software must also be made available in Source Code Form.

3.3. Distribution of a Larger Work
You may create and distribute a Larger Work under terms of Your choice,
provided that You also comply with the requirements of this License for
the Covered Software.

4. Inability to Comply Due to Statute or Regulation
If it is impossible for You to comply with any of the terms of this
License with respect to some or all of the Covered Software due to
statute, judicial order, or regulation then You must: (a) comply with
the terms of this License to the maximum extent possible; and (b)
describe the limitations and the code they affect.

5. Termination

5.1. The rights granted under this License will terminate automatically
if You fail to comply with any of its terms.

5.2. If You initiate litigation against any entity by asserting a patent
infringement claim against the entity, then You lose all rights granted
under this License.

6. Disclaimer of Warranty
Covered Software is provided under this License on an "as is" basis,
without warranty of any kind.

7. Limitation of Liability
Under no circumstances and under no legal theory shall any Contributor
be liable to You for any damages.

8. Litigation
Any litigation relating to this License may be brought only in the courts
of a jurisdiction where the defendant maintains its principal place of business.

9. Miscellaneous
This License represents the complete agreement concerning the subject matter hereof.

10. Versions of the License
10.1. New Versions — Mozilla Foundation is the license steward.
10.2. Effect of New Versions — You may use Covered Software under the terms
of the version of the License under which You originally received it,
or under the terms of any subsequent version published by the license steward.`,
  },

  // ── BSD-3-Clause ──
  {
    license: "BSD 3-Clause License",
    packages: [
      { name: "alloc-no-stdlib", version: "2.0.4" },
      { name: "alloc-stdlib", version: "0.2.2" },
      { name: "brotli", version: "8.0.2" },
      { name: "brotli-decompressor", version: "5.0.0" },
      { name: "num_enum", version: "0.7.5" },
    ],
    text: `BSD 3-Clause License

Copyright (c) <year>, <copyright holder>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.`,
  },

  // ── ISC ──
  {
    license: "ISC License",
    packages: [
      { name: "libloading", version: "0.7.4" },
    ],
    text: `ISC License

Copyright (c) <year>, <copyright holder>

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.`,
  },

  // ── Unicode-3.0 ──
  {
    license: "Unicode License v3",
    packages: [
      { name: "icu_collections", version: "2.1.1" },
      { name: "icu_normalizer", version: "2.1.1" },
      { name: "icu_properties", version: "2.1.2" },
      { name: "icu_provider", version: "2.1.1" },
      { name: "icu_locale_core", version: "2.1.1" },
      { name: "tinystr", version: "0.8.2" },
      { name: "litemap", version: "0.8.1" },
    ],
    text: `UNICODE LICENSE V3

COPYRIGHT AND PERMISSION NOTICE

Copyright © 1991-2024 Unicode, Inc.

NOTICE TO USER: Carefully read the following legal agreement. BY
DOWNLOADING, INSTALLING, COPYING OR OTHERWISE USING DATA FILES, AND/OR
SOFTWARE, YOU UNEQUIVOCALLY ACCEPT, AND AGREE TO BE BOUND BY, ALL OF THE
TERMS AND CONDITIONS OF THIS AGREEMENT. IF YOU DO NOT AGREE, DO NOT
DOWNLOAD, INSTALL, COPY, DISTRIBUTE OR USE THE DATA FILES OR SOFTWARE.

Permission is hereby granted, free of charge, to any person obtaining a
copy of data files and any associated documentation (the "Data Files") or
software and any associated documentation (the "Software") to deal in the
Data Files or Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, and/or sell
copies of the Data Files or Software, and to permit persons to whom the
Data Files or Software are furnished to do so, provided that either (a)
this copyright and permission notice appear with all copies of the Data
Files or Software, or (b) this copyright and permission notice appear in
associated Documentation.

THE DATA FILES AND SOFTWARE ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT OF
THIRD PARTY RIGHTS.`,
  },

  // ── Zlib ──
  {
    license: "Zlib License",
    packages: [
      { name: "bytemuck", version: "1.25.0" },
      { name: "foldhash", version: "0.1.5" },
      { name: "dispatch2", version: "0.3.0" },
      { name: "objc2-app-kit", version: "0.3.2" },
      { name: "objc2-core-foundation", version: "0.3.2" },
      { name: "objc2-core-graphics", version: "0.3.2" },
    ],
    text: `zlib License

Copyright (c) <year> <copyright holders>

This software is provided 'as-is', without any express or implied warranty.
In no event will the authors be held liable for any damages arising from the
use of this software.

Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it
freely, subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not
   claim that you wrote the original software. If you use this software
   in a product, an acknowledgment in the product documentation would be
   appreciated but is not required.

2. Altered source versions must be plainly marked as such, and must not
   be misrepresented as being the original software.

3. This notice may not be removed or altered from any source distribution.`,
  },

  // ── 0BSD ──
  {
    license: "Zero-Clause BSD (0BSD)",
    packages: [
      { name: "adler2", version: "2.0.1" },
    ],
    text: `Zero-Clause BSD (0BSD)

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.`,
  },
];
