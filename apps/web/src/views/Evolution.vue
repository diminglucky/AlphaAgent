<template>
  <div class="evolution-page">
    <div class="hero-card">
      <div>
        <div class="eyebrow">Auto Evolution</div>
        <h2>模型进化中枢</h2>
        <p>把每次扫描推荐变成可验证样本，到期后回看真实涨幅，并用结果校准下一版推荐概率。</p>
      </div>
      <div class="hero-actions">
        <el-button :loading="loading" @click="loadAll">刷新</el-button>
        <el-button type="primary" :loading="validating" @click="validateDue(false)">验证到期预测</el-button>
        <el-button type="primary" plain :loading="autoScanning" @click="autoScanOnce">自动采样一次</el-button>
        <el-button type="success" plain :loading="autoCycling" @click="autoCycle">自动进化检查</el-button>
        <el-button type="warning" :loading="evolving" @click="evolve(false)">生成候选模型</el-button>
        <el-button type="danger" plain :loading="evolving" @click="evolve(true)">进化并启用</el-button>
      </div>
    </div>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
    />

    <div class="metric-grid">
      <div class="metric-card active">
        <div class="metric-label">当前模型</div>
        <div class="metric-value">{{ activeModel?.version || '--' }}</div>
        <div class="metric-sub">{{ activeModel?.status || '未初始化' }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">已验证样本</div>
        <div class="metric-value">{{ counts.validated || 0 }}</div>
        <div class="metric-sub">总样本 {{ counts.total_predictions || 0 }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">待验证</div>
        <div class="metric-value">{{ counts.pending || 0 }}</div>
        <div class="metric-sub">已到期 {{ counts.due || 0 }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">命中率</div>
        <div class="metric-value">{{ pct(metrics.success_rate) }}</div>
        <div class="metric-sub">平均收益 {{ signed(metrics.avg_return_pct) }}%</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">概率校准误差</div>
        <div class="metric-value">{{ pct(metrics.calibration_error) }}</div>
        <div class="metric-sub">越低越好</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">LLM 用量</div>
        <div class="metric-value">{{ llmSummary.total_tokens || 0 }}</div>
        <div class="metric-sub">
          {{ llmSummary.calls || 0 }} 次调用 · ${{ fmtCost(llmSummary.estimated_cost_usd) }}
        </div>
      </div>
    </div>

    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="card-header">
          <span>自动进化控制台</span>
          <div class="table-actions">
            <el-tag :type="evolutionEffective.running ? 'success' : 'info'" size="small" effect="dark">
              {{ evolutionEffective.running ? '后台验证运行中' : '后台验证已关闭' }}
            </el-tag>
            <el-tag :type="evolutionEffective.auto_scan_running ? 'success' : 'info'" size="small" effect="dark">
              {{ evolutionEffective.auto_scan_running ? '自动采样运行中' : '自动采样已关闭' }}
            </el-tag>
            <el-button size="small" plain :loading="savingConfig" @click="loadEvolutionConfig">刷新配置</el-button>
          </div>
        </div>
      </template>
      <el-form :model="evolutionForm" label-width="150px" class="evolution-config-form">
        <div class="config-grid">
          <el-form-item label="验证间隔（秒）">
            <el-input-number v-model="evolutionForm.validate_interval_seconds" :min="0" :max="604800" :step="3600" />
            <div class="field-hint">0 表示关闭后台自动验证；保存后会重启验证循环。</div>
          </el-form-item>
          <el-form-item label="启动延迟（秒）">
            <el-input-number v-model="evolutionForm.validate_initial_delay_seconds" :min="0" :max="86400" :step="30" />
          </el-form-item>
          <el-form-item label="固定验证时间">
            <el-input v-model="evolutionForm.validate_time" placeholder="HH:MM，例如 15:30" clearable style="width:220px" />
            <div class="field-hint">留空时按验证间隔运行；填写后按服务器本地时间每天触发一次。</div>
          </el-form-item>
          <el-form-item label="单次验证上限">
            <el-input-number v-model="evolutionForm.validate_limit" :min="1" :max="5000" :step="50" />
          </el-form-item>
          <el-form-item label="失败告警">
            <el-switch v-model="evolutionForm.failure_alert_enabled" />
            <div class="field-hint">后台自动验证或自动采样失败时通过飞书通知；需先配置飞书 Webhook。</div>
          </el-form-item>
          <el-form-item label="告警冷却（秒）">
            <el-input-number
              v-model="evolutionForm.failure_alert_cooldown_seconds"
              :min="0"
              :max="604800"
              :step="600"
              :disabled="!evolutionForm.failure_alert_enabled"
            />
            <div class="field-hint">按失败类型分别冷却，避免数据源故障时重复刷屏；0 表示不冷却。</div>
          </el-form-item>
          <el-form-item label="自动采样">
            <el-switch v-model="evolutionForm.auto_scan_enabled" />
            <div class="field-hint">开启后后台定时运行 Scanner 并写入新的待验证预测样本；默认关闭以避免全市场扫描成本。</div>
          </el-form-item>
          <el-form-item label="采样间隔（秒）">
            <el-input-number v-model="evolutionForm.auto_scan_interval_seconds" :min="0" :max="604800" :step="3600" />
            <div class="field-hint">0 表示关闭后台自动采样；手动“自动采样一次”不受此开关影响。</div>
          </el-form-item>
          <el-form-item label="采样返回数量">
            <el-input-number v-model="evolutionForm.auto_scan_top_n" :min="1" :max="200" :step="5" />
          </el-form-item>
          <el-form-item label="采样最低分">
            <el-input-number v-model="evolutionForm.auto_scan_min_score" :min="0" :max="100" :step="5" />
          </el-form-item>
          <el-form-item label="采样候选池">
            <el-input-number v-model="evolutionForm.auto_scan_candidate_pool" :min="1" :max="1000" :step="20" />
          </el-form-item>
          <el-form-item label="采样目标周期">
            <el-select v-model="evolutionForm.auto_scan_target_horizon_days" style="width:180px">
              <el-option :value="0" label="自动最佳" />
              <el-option :value="3" label="3 日概率" />
              <el-option :value="5" label="5 日概率" />
              <el-option :value="10" label="10 日概率" />
              <el-option :value="20" label="20 日概率" />
            </el-select>
          </el-form-item>
          <el-form-item label="采样基本面">
            <el-switch v-model="evolutionForm.auto_scan_enable_fundamental" />
          </el-form-item>
          <el-form-item label="采样 LLM">
            <el-switch v-model="evolutionForm.auto_scan_enable_llm" />
            <div class="field-hint">默认关闭，避免自动后台循环产生不可控 LLM 调用。</div>
          </el-form-item>
          <el-form-item label="采样 LLM 数量">
            <el-input-number
              v-model="evolutionForm.auto_scan_llm_top_n"
              :min="1"
              :max="50"
              :step="1"
              :disabled="!evolutionForm.auto_scan_enable_llm"
            />
          </el-form-item>
          <el-form-item label="自动进化">
            <el-switch v-model="evolutionForm.auto_evolve_enabled" />
          </el-form-item>
          <el-form-item label="晋升最小样本">
            <el-input-number v-model="evolutionForm.auto_evolve_min_samples" :min="1" :max="100000" :step="10" />
          </el-form-item>
          <el-form-item label="晋升最低命中率">
            <el-input-number v-model="evolutionForm.auto_promote_min_success_rate" :min="0" :max="1" :step="0.01" />
          </el-form-item>
          <el-form-item label="晋升最低收益%">
            <el-input-number v-model="evolutionForm.auto_promote_min_avg_return_pct" :min="-100" :max="100" :step="0.1" />
          </el-form-item>
          <el-form-item label="晋升最大 Brier">
            <el-input-number v-model="evolutionForm.auto_promote_max_brier_score" :min="0" :max="1" :step="0.01" />
          </el-form-item>
          <el-form-item label="晋升最大校准误差">
            <el-input-number v-model="evolutionForm.auto_promote_max_calibration_error" :min="0" :max="1" :step="0.01" />
          </el-form-item>
          <el-form-item label="WF 最小样本">
            <el-input-number v-model="evolutionForm.auto_walk_forward_min_samples" :min="1" :max="100000" :step="1" />
          </el-form-item>
          <el-form-item label="WF 最小日期数">
            <el-input-number v-model="evolutionForm.auto_walk_forward_min_dates" :min="1" :max="100000" :step="1" />
          </el-form-item>
          <el-form-item label="WF 最低盈利折数">
            <el-input-number
              v-model="evolutionForm.auto_walk_forward_min_profitable_folds"
              :min="0"
              :max="1"
              :step="0.01"
            />
          </el-form-item>
          <el-form-item label="WF 收益容差">
            <el-input-number
              v-model="evolutionForm.auto_walk_forward_return_tolerance"
              :min="0"
              :max="1"
              :step="0.001"
            />
            <div class="field-hint">比例值：0.001 表示允许候选回放收益比基线低 0.1%。</div>
          </el-form-item>
          <el-form-item label="WF 一致性容差">
            <el-input-number
              v-model="evolutionForm.auto_walk_forward_consistency_tolerance"
              :min="0"
              :max="1"
              :step="0.01"
            />
            <div class="field-hint">比例值：0.02 表示允许一致性评分比基线低 2%。</div>
          </el-form-item>
          <el-form-item label="WF 回撤容差">
            <el-input-number
              v-model="evolutionForm.auto_walk_forward_drawdown_tolerance"
              :min="0"
              :max="1"
              :step="0.01"
            />
            <div class="field-hint">比例值：0.03 表示允许候选平均回撤比基线高 3%。</div>
          </el-form-item>
          <el-form-item label="自动回滚">
            <el-switch v-model="evolutionForm.auto_rollback_enabled" />
          </el-form-item>
          <el-form-item label="回滚最小样本">
            <el-input-number v-model="evolutionForm.auto_rollback_min_samples" :min="1" :max="100000" :step="10" />
          </el-form-item>
          <el-form-item label="回滚最低命中率">
            <el-input-number v-model="evolutionForm.auto_rollback_min_success_rate" :min="0" :max="1" :step="0.01" />
          </el-form-item>
          <el-form-item label="回滚最低收益%">
            <el-input-number v-model="evolutionForm.auto_rollback_min_avg_return_pct" :min="-100" :max="100" :step="0.1" />
          </el-form-item>
          <el-form-item label="回滚最大 Brier">
            <el-input-number v-model="evolutionForm.auto_rollback_max_brier_score" :min="0" :max="1" :step="0.01" />
          </el-form-item>
        </div>
      </el-form>
      <div class="config-actions">
        <el-button type="primary" :loading="savingConfig" @click="saveEvolutionConfig">保存并重启后台循环</el-button>
        <el-button plain :loading="savingConfig" @click="resetEvolutionConfig">重置为环境变量</el-button>
        <span class="muted">运行时覆盖项 {{ Object.keys(evolutionRuntime || {}).length }} 个</span>
      </div>
      <div v-if="autoScanLastRun" class="auto-scan-status">
        <div>
          <span class="muted">最近自动采样</span>
          <el-tag :type="autoScanLastRun.ok ? 'success' : 'danger'" size="small" effect="dark">
            {{ autoScanLastRun.ok ? '成功' : '失败' }}
          </el-tag>
        </div>
        <div class="auto-scan-meta">
          <span>完成 {{ fmtTime(autoScanLastRun.finished_at) }}</span>
          <span>扫描批次 {{ autoScanLastRun.scan_run_id || '--' }}</span>
          <span>推荐 {{ autoScanLastRun.results || 0 }}</span>
          <span>新增样本 {{ autoScanLastRun.predictions_created || 0 }}</span>
          <span>LLM {{ autoScanLastRun.llm_status || 'disabled' }}</span>
        </div>
        <div v-if="autoScanLastRun.error" class="auto-scan-error">{{ autoScanLastRun.error }}</div>
      </div>
      <div v-if="validationLastRun" class="auto-scan-status">
        <div>
          <span class="muted">最近自动验证 / 进化</span>
          <el-tag :type="validationLastRun.ok ? 'success' : 'danger'" size="small" effect="dark">
            {{ validationLastRun.ok ? '成功' : '失败' }}
          </el-tag>
        </div>
        <div class="auto-scan-meta">
          <span>完成 {{ fmtTime(validationLastRun.finished_at) }}</span>
          <span>成交检查 {{ validationLastRun.trade_result?.checked || 0 }}</span>
          <span>执行样本 {{ validationLastRun.trade_result?.predictions_created || 0 }}</span>
          <span>退出验证 {{ validationLastRun.trade_result?.exits_recorded || 0 }}</span>
          <span>预测检查 {{ validationLastRun.validation_result?.checked || 0 }}</span>
          <span>已验证 {{ validationLastRun.validation_result?.validated || 0 }}</span>
          <span>错误 {{ validationLastRun.validation_result?.errors || 0 }}</span>
          <span>进化 {{ runStatusLabel(validationLastRun.auto_cycle_result?.status) }}</span>
          <span v-if="validationLastRun.auto_cycle_result?.evaluated_predictions !== undefined">
            样本 {{ validationLastRun.auto_cycle_result.evaluated_predictions }}
          </span>
        </div>
        <div v-if="validationLastRun.auto_cycle_result?.reasons?.length" class="auto-scan-error">
          {{ validationLastRun.auto_cycle_result.reasons.join('；') }}
        </div>
        <div v-if="validationLastRun.error" class="auto-scan-error">{{ validationLastRun.error }}</div>
      </div>
      <div v-if="failureAlertLastEvent" class="auto-scan-status">
        <div>
          <span class="muted">最近失败告警</span>
          <el-tag :type="alertStatusType(failureAlertLastEvent.alert_status)" size="small" effect="dark">
            {{ alertStatusLabel(failureAlertLastEvent.alert_status) }}
          </el-tag>
        </div>
        <div class="auto-scan-meta">
          <span>任务 {{ failureAlertLastEvent.type || '--' }}</span>
          <span>发生 {{ fmtTime(failureAlertLastEvent.created_at) }}</span>
          <span>冷却 {{ failureAlertLastEvent.cooldown_seconds || 0 }}s</span>
          <span v-if="failureAlertLastEvent.last_sent_at">上次发送 {{ fmtTime(failureAlertLastEvent.last_sent_at) }}</span>
          <span v-if="failureAlertLastEvent.next_allowed_at">下次允许 {{ fmtTime(failureAlertLastEvent.next_allowed_at) }}</span>
        </div>
        <div v-if="failureAlertLastEvent.error" class="auto-scan-error">{{ failureAlertLastEvent.error }}</div>
      </div>
    </el-card>

    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="card-header">
              <span>按预测周期表现</span>
              <el-tag size="small" type="info" effect="plain">3 / 5 / 10 / 20 日</el-tag>
            </div>
          </template>
          <el-empty v-if="!horizonRows.length" description="暂无已验证样本" />
          <div v-else class="horizon-list">
            <div v-for="row in horizonRows" :key="row.horizon_days" class="horizon-item">
              <div class="horizon-title">
                <span>{{ row.horizon_days }} 日</span>
                <span>{{ row.sample_count }} 个样本</span>
              </div>
              <div class="horizon-bar">
                <el-progress
                  :percentage="Math.round((row.success_rate || 0) * 100)"
                  :stroke-width="8"
                  :show-text="false"
                  :color="progressColor(row.success_rate)"
                />
              </div>
              <div class="horizon-meta">
                <span>命中 {{ pct(row.success_rate) }}</span>
                <span>收盘收益 {{ signed(row.avg_return_pct) }}%</span>
                <span>最大涨幅 {{ signed(row.avg_max_return_pct) }}%</span>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="card-header">
              <span>最近扫描批次</span>
              <span class="muted">每次扫描会自动写入预测样本</span>
            </div>
          </template>
          <el-table :data="summary?.latest_scan_runs || []" size="small" height="276">
            <el-table-column prop="id" label="批次" width="70" />
            <el-table-column label="时间" min-width="150">
              <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column prop="result_count" label="推荐" width="70" />
            <el-table-column prop="rejected_count" label="否决" width="70" />
            <el-table-column prop="llm_status" label="LLM" width="90" />
            <el-table-column label="耗时" width="90">
              <template #default="{ row }">{{ Math.round((row.elapsed_ms || 0) / 1000) }}s</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="card-header">
          <span>最近两次扫描对比</span>
          <span class="muted">看哪些股票连续被推荐、哪些是新出现机会</span>
        </div>
      </template>
      <el-empty v-if="!comparison?.ready" description="至少需要两次已落库扫描结果" />
      <div v-else class="compare-panel">
        <div class="compare-stats">
          <div class="compare-stat">
            <span>本次推荐</span>
            <b>{{ comparison.counts?.base || 0 }}</b>
          </div>
          <div class="compare-stat new">
            <span>新增</span>
            <b>{{ comparison.counts?.new || 0 }}</b>
          </div>
          <div class="compare-stat overlap">
            <span>连续推荐</span>
            <b>{{ comparison.counts?.overlap || 0 }}</b>
          </div>
          <div class="compare-stat dropped">
            <span>掉队</span>
            <b>{{ comparison.counts?.dropped || 0 }}</b>
          </div>
        </div>
        <div class="compare-columns">
          <div class="compare-col">
            <div class="compare-title">新增机会</div>
            <div v-if="!comparison.new?.length" class="muted">无</div>
            <div v-for="s in comparison.new || []" :key="s.symbol" class="compare-stock">
              <span>{{ s.name || s.symbol }}</span>
              <b>{{ s.probability_pct }}%</b>
            </div>
          </div>
          <div class="compare-col">
            <div class="compare-title">连续推荐</div>
            <div v-if="!comparison.overlap?.length" class="muted">无</div>
            <div v-for="s in comparison.overlap || []" :key="s.symbol" class="compare-stock strong">
              <span>{{ s.name || s.symbol }}</span>
              <b>{{ s.probability_pct }}%</b>
            </div>
          </div>
          <div class="compare-col">
            <div class="compare-title">上次有、本次掉队</div>
            <div v-if="!comparison.dropped?.length" class="muted">无</div>
            <div v-for="s in comparison.dropped || []" :key="s.symbol" class="compare-stock muted-stock">
              <span>{{ s.name || s.symbol }}</span>
              <b>{{ s.probability_pct }}%</b>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="card-header">
          <span>自动进化决策记录</span>
          <span class="muted">记录自动晋升、阻断和回滚原因</span>
        </div>
      </template>
      <el-table :data="summary?.latest_evolution_runs || []" size="small" height="260">
        <el-table-column label="时间" min-width="150">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-tag :type="runStatusType(row.status)" size="small" effect="dark">
              {{ runStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="evaluated_predictions" label="样本" width="80" />
        <el-table-column label="命中率" width="90">
          <template #default="{ row }">{{ pct(row.success_rate) }}</template>
        </el-table-column>
        <el-table-column label="平均收益" width="100">
          <template #default="{ row }">{{ signed(row.avg_return_pct) }}%</template>
        </el-table-column>
        <el-table-column label="门槛" width="220">
          <template #default="{ row }">
            <div class="gate-tags">
              <el-tag :type="gateTagType(row.summary?.holdout_passed)" size="small" effect="dark">
                Holdout {{ gateLabel(row.summary?.holdout_passed) }}
              </el-tag>
              <el-tag :type="gateTagType(row.summary?.signal_quality_passed)" size="small" effect="dark">
                Signal {{ gateLabel(row.summary?.signal_quality_passed) }}
              </el-tag>
              <el-tag
                :type="gateTagType(row.summary?.walk_forward_passed, row.summary?.walk_forward_validation?.ready)"
                size="small"
                effect="dark"
              >
                WF {{ gateLabel(row.summary?.walk_forward_passed, row.summary?.walk_forward_validation?.ready) }}
              </el-tag>
            </div>
            <div v-if="row.summary?.walk_forward_validation?.ready" class="wf-meta">
              <span>样本 {{ row.summary.walk_forward_validation.sample_count }}</span>
              <span>日期 {{ row.summary.walk_forward_validation.unique_dates }}</span>
              <span>折数 {{ row.summary.walk_forward_validation.baseline?.n_folds || 0 }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="原因 / 决策" min-width="260">
          <template #default="{ row }">
            <div class="decision-stack">
              <span class="decision-text">{{ decisionText(row) }}</span>
              <div v-if="row.summary?.walk_forward_validation?.ready" class="wf-detail">
                <span>阈值：{{ wfThresholdText(row.summary.walk_forward_validation.thresholds) }}</span>
                <span>
                  对比：候选 {{ signedPctRatio(row.summary.walk_forward_validation.candidate?.oos_total_return_mean) }}%
                  / 基线 {{ signedPctRatio(row.summary.walk_forward_validation.baseline?.oos_total_return_mean) }}%
                </span>
                <span>
                  盈利折数：{{ pct(row.summary.walk_forward_validation.candidate?.pct_profitable_folds) }}
                  / 基线 {{ pct(row.summary.walk_forward_validation.baseline?.pct_profitable_folds) }}
                </span>
                <span>
                  一致性：{{ pct(row.summary.walk_forward_validation.candidate?.consistency_score) }}
                  / 基线 {{ pct(row.summary.walk_forward_validation.baseline?.consistency_score) }}
                </span>
                <span>
                  回撤：{{ pct(row.summary.walk_forward_validation.candidate?.oos_max_drawdown_mean) }}
                  / 基线 {{ pct(row.summary.walk_forward_validation.baseline?.oos_max_drawdown_mean) }}
                </span>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="card-header">
          <span>预测样本</span>
          <div class="table-actions">
            <el-select v-model="filters.status" size="small" style="width:120px" @change="loadPredictions">
              <el-option label="全部" value="" />
              <el-option label="待验证" value="pending" />
              <el-option label="已验证" value="validated" />
            </el-select>
            <el-select v-model="filters.horizon_days" size="small" style="width:120px" @change="loadPredictions">
              <el-option label="全部周期" :value="null" />
              <el-option label="3 日" :value="3" />
              <el-option label="5 日" :value="5" />
              <el-option label="10 日" :value="10" />
              <el-option label="20 日" :value="20" />
            </el-select>
          </div>
        </div>
      </template>

      <el-table :data="predictions" v-loading="loadingPredictions" height="420">
        <el-table-column label="股票" min-width="150">
          <template #default="{ row }">
            <div class="stock-cell">
              <span class="stock-name">{{ row.name || row.symbol }}</span>
              <span class="stock-code">{{ row.symbol }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="周期" width="80">
          <template #default="{ row }">{{ row.horizon_days }} 日</template>
        </el-table-column>
        <el-table-column label="上涨概率" width="110">
          <template #default="{ row }">
            <span class="prob">{{ row.probability_pct }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="目标" width="90">
          <template #default="{ row }">+{{ fmt(row.target_return_pct) }}%</template>
        </el-table-column>
        <el-table-column label="预期收益" width="100">
          <template #default="{ row }">
            <span :class="row.expected_return_pct >= 0 ? 'up' : 'down'">
              {{ signed(row.expected_return_pct) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'validated' ? 'success' : 'info'" size="small" effect="dark">
              {{ row.status === 'validated' ? '已验证' : '待验证' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="结果" width="120">
          <template #default="{ row }">
            <span v-if="!row.outcome" class="muted">未到期</span>
            <el-tag v-else :type="row.outcome.success ? 'success' : 'danger'" size="small" effect="dark">
              {{ row.outcome.success ? '命中' : '未命中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="真实收益" width="110">
          <template #default="{ row }">
            <span v-if="row.outcome" :class="row.outcome.close_return_pct >= 0 ? 'up' : 'down'">
              {{ signed(row.outcome.close_return_pct) }}%
            </span>
            <span v-else class="muted">--</span>
          </template>
        </el-table-column>
        <el-table-column label="到期" min-width="150">
          <template #default="{ row }">{{ fmtTime(row.due_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'

defineOptions({ name: 'Evolution' })

const loading = ref(false)
const loadingPredictions = ref(false)
const validating = ref(false)
const evolving = ref(false)
const autoCycling = ref(false)
const autoScanning = ref(false)
const savingConfig = ref(false)
const error = ref('')
const summary = ref(null)
const predictions = ref([])
const comparison = ref(null)
const llmUsage = ref(null)
const evolutionConfig = ref(null)
const filters = reactive({
  status: '',
  horizon_days: null,
})
const evolutionForm = reactive({
  validate_interval_seconds: 86400,
  validate_initial_delay_seconds: 60,
  validate_time: '',
  validate_limit: 200,
  failure_alert_enabled: true,
  failure_alert_cooldown_seconds: 3600,
  auto_scan_enabled: false,
  auto_scan_interval_seconds: 86400,
  auto_scan_top_n: 20,
  auto_scan_min_score: 50,
  auto_scan_candidate_pool: 100,
  auto_scan_enable_fundamental: true,
  auto_scan_enable_llm: false,
  auto_scan_llm_top_n: 8,
  auto_scan_target_horizon_days: 0,
  auto_evolve_enabled: true,
  auto_evolve_min_samples: 60,
  auto_promote_min_success_rate: 0.52,
  auto_promote_min_avg_return_pct: 0,
  auto_promote_max_brier_score: 0.28,
  auto_promote_max_calibration_error: 0.18,
  auto_walk_forward_min_samples: 12,
  auto_walk_forward_min_dates: 12,
  auto_walk_forward_min_profitable_folds: 0.5,
  auto_walk_forward_return_tolerance: 0.001,
  auto_walk_forward_consistency_tolerance: 0.02,
  auto_walk_forward_drawdown_tolerance: 0.03,
  auto_rollback_enabled: true,
  auto_rollback_min_samples: 30,
  auto_rollback_min_success_rate: 0.4,
  auto_rollback_min_avg_return_pct: -2,
  auto_rollback_max_brier_score: 0.4,
})

const activeModel = computed(() => summary.value?.active_model || null)
const counts = computed(() => summary.value?.counts || {})
const metrics = computed(() => summary.value?.metrics || {})
const horizonRows = computed(() => metrics.value?.by_horizon || [])
const llmSummary = computed(() => llmUsage.value?.summary || {})
const evolutionEffective = computed(() => evolutionConfig.value?.effective || {})
const evolutionRuntime = computed(() => evolutionConfig.value?.runtime_override || {})
const autoScanLastRun = computed(() => evolutionEffective.value?.auto_scan_last_run || null)
const validationLastRun = computed(() => evolutionEffective.value?.validation_last_run || null)
const failureAlertLastEvent = computed(() => evolutionEffective.value?.failure_alert_last_event || null)

function fmt(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(2) : '--'
}

function pct(v) {
  const n = Number(v)
  return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : '--'
}

function signed(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}`
}

function signedPctRatio(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  return `${n >= 0 ? '+' : ''}${(n * 100).toFixed(2)}`
}

function fmtTime(v) {
  if (!v) return '--'
  return new Date(v).toLocaleString('zh-CN', { hour12: false })
}

function fmtCost(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(6) : '0.000000'
}

function progressColor(v) {
  if (v >= 0.6) return '#f56c6c'
  if (v >= 0.4) return '#e6a23c'
  return '#67c23a'
}

function runStatusType(status) {
  if (status === 'auto_promoted' || status === 'completed') return 'success'
  if (status === 'auto_rolled_back') return 'danger'
  if (status === 'auto_blocked' || status === 'insufficient_data') return 'warning'
  return 'info'
}

function runStatusLabel(status) {
  const labels = {
    completed: '手动进化',
    insufficient_data: '样本不足',
    auto_blocked: '自动阻断',
    auto_promoted: '自动晋升',
    auto_rolled_back: '自动回滚',
  }
  return labels[status] || status || '--'
}

function alertStatusType(status) {
  if (status === 'sent') return 'danger'
  if (status === 'suppressed') return 'warning'
  if (status === 'disabled') return 'info'
  if (status === 'not_configured') return 'info'
  return 'info'
}

function alertStatusLabel(status) {
  const labels = {
    sent: '已发送',
    suppressed: '冷却抑制',
    disabled: '已关闭',
    not_configured: '未配置飞书',
  }
  return labels[status] || status || '--'
}

function decisionText(row) {
  const summary = row?.summary || {}
  const reasons = summary.reasons || []
  if (reasons.length) return reasons.join('；')
  const gates = []
  if (summary.holdout_passed !== undefined) gates.push(`Holdout ${summary.holdout_passed ? '通过' : '阻断'}`)
  if (summary.signal_quality_passed !== undefined) gates.push(`Signal ${summary.signal_quality_passed ? '通过' : '阻断'}`)
  if (summary.walk_forward_passed !== undefined) gates.push(`WF ${summary.walk_forward_passed ? '通过' : '阻断'}`)
  const wf = summary.walk_forward_validation || {}
  if (wf.ready && wf.candidate && wf.baseline) {
    gates.push(
      `回放 ${signedPctRatio(wf.candidate.oos_total_return_mean)}% / ${signedPctRatio(wf.baseline.oos_total_return_mean)}%`
    )
  }
  if (gates.length) return gates.join(' · ')
  if (summary.candidate_version) return `候选 ${summary.candidate_version} 已启用`
  if (summary.restored_model) return `恢复 ${summary.restored_model}，回滚 ${summary.rolled_back_model}`
  if (summary.reason) return summary.reason
  return '--'
}

function gateTagType(value, ready = true) {
  if (!ready) return 'info'
  if (value === true) return 'success'
  if (value === false) return 'danger'
  return 'info'
}

function gateLabel(value, ready = true) {
  if (!ready) return 'N/A'
  if (value === true) return '通过'
  if (value === false) return '阻断'
  return '--'
}

function wfThresholdText(thresholds) {
  if (!thresholds) return '--'
  return [
    `样本>=${thresholds.min_samples}`,
    `日期>=${thresholds.min_dates}`,
    `盈利折数>=${pct(thresholds.min_profitable_folds)}`,
    `收益容差<=${pct(thresholds.return_tolerance)}`,
    `一致性容差<=${pct(thresholds.consistency_tolerance)}`,
    `回撤容差<=${pct(thresholds.drawdown_tolerance)}`,
  ].join(' · ')
}

async function loadSummary() {
  summary.value = await api.evolutionSummary()
}

async function loadPredictions() {
  loadingPredictions.value = true
  try {
    predictions.value = await api.evolutionPredictions({
      status: filters.status || undefined,
      horizon_days: filters.horizon_days || undefined,
      limit: 120,
    })
  } finally {
    loadingPredictions.value = false
  }
}

async function loadComparison() {
  comparison.value = await api.evolutionCompare()
}

async function loadUsage() {
  llmUsage.value = await api.llmUsage({ limit: 100 })
}

function applyEvolutionConfig(config) {
  evolutionConfig.value = config
  const eff = config?.effective || {}
  for (const key of Object.keys(evolutionForm)) {
    if (eff[key] !== undefined) evolutionForm[key] = eff[key]
  }
}

async function loadEvolutionConfig() {
  applyEvolutionConfig(await api.evolutionConfig())
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadSummary(), loadPredictions(), loadComparison(), loadUsage(), loadEvolutionConfig()])
  } catch (e) {
    error.value = `加载模型进化数据失败：${e.message}`
  } finally {
    loading.value = false
  }
}

async function saveEvolutionConfig() {
  savingConfig.value = true
  error.value = ''
  try {
    const saved = await api.evolutionConfigSet({ ...evolutionForm })
    applyEvolutionConfig(saved)
    ElMessage.success('自动进化配置已保存，后台循环已重启')
  } catch (e) {
    error.value = `保存自动进化配置失败：${e.message}`
  } finally {
    savingConfig.value = false
  }
}

async function resetEvolutionConfig() {
  savingConfig.value = true
  error.value = ''
  try {
    const reset = await api.evolutionConfigReset()
    applyEvolutionConfig(reset)
    ElMessage.success('已重置为环境变量配置，后台循环已重启')
  } catch (e) {
    error.value = `重置自动进化配置失败：${e.message}`
  } finally {
    savingConfig.value = false
  }
}

async function autoScanOnce() {
  autoScanning.value = true
  error.value = ''
  try {
    const ret = await api.evolutionAutoScan()
    if (ret.ok) {
      ElMessage.success(`自动采样完成：推荐 ${ret.results || 0}，新增样本 ${ret.predictions_created || 0}`)
    } else {
      ElMessage.warning(`自动采样失败：${ret.error || '未知错误'}`)
    }
    await loadAll()
  } catch (e) {
    error.value = `自动采样失败：${e.message}`
  } finally {
    autoScanning.value = false
  }
}

async function validateDue(force) {
  validating.value = true
  error.value = ''
  try {
    const ret = await api.evolutionValidate({ limit: 300, force })
    ElMessage.success(`验证完成：检查 ${ret.checked}，验证 ${ret.validated}，跳过 ${ret.skipped}`)
    await loadAll()
  } catch (e) {
    error.value = `验证失败：${e.message}`
  } finally {
    validating.value = false
  }
}

async function evolve(promote) {
  evolving.value = true
  error.value = ''
  try {
    const ret = await api.evolutionEvolve({ promote })
    if (ret.status === 'insufficient_data') {
      ElMessage.warning(`样本不足：${ret.evaluated_predictions} / ${ret.min_samples}`)
    } else {
      ElMessage.success(promote ? '新模型已启用' : '候选模型已生成')
    }
    await loadAll()
  } catch (e) {
    error.value = `进化失败：${e.message}`
  } finally {
    evolving.value = false
  }
}

async function autoCycle() {
  autoCycling.value = true
  error.value = ''
  try {
    const ret = await api.evolutionAutoCycle()
    if (ret.status === 'auto_promoted') {
      ElMessage.success(`自动晋升完成：${ret.active_model?.version || '新模型'}`)
    } else if (ret.status === 'auto_rolled_back') {
      ElMessage.warning(`已自动回滚到：${ret.active_model?.version || '父模型'}`)
    } else if (ret.status === 'auto_blocked') {
      ElMessage.warning(`自动进化被阻断：${(ret.reasons || []).join('；') || '未达到质量门槛'}`)
    } else if (ret.status === 'insufficient_data') {
      ElMessage.info(`样本不足：${ret.evaluated_predictions} / ${ret.min_samples}`)
    } else {
      ElMessage.info(`自动进化状态：${ret.status}`)
    }
    await loadAll()
  } catch (e) {
    error.value = `自动进化检查失败：${e.message}`
  } finally {
    autoCycling.value = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.evolution-page { display:flex; flex-direction:column; gap:16px; }
.hero-card {
  display:flex;
  justify-content:space-between;
  align-items:flex-start;
  gap:18px;
  padding:22px;
  border-radius:18px;
  background:
    radial-gradient(circle at 12% 0%, rgba(64, 158, 255, .22), transparent 30%),
    linear-gradient(135deg, #18213d, #111827 55%, #1a1a2e);
  border:1px solid #2a3a64;
}
.eyebrow { color:#7db7ff; text-transform:uppercase; font-size:12px; letter-spacing:.14em; font-weight:800; }
.hero-card h2 { margin:6px 0; font-size:30px; color:#fff; }
.hero-card p { color:#a9b4c8; max-width:680px; line-height:1.7; }
.hero-actions { display:flex; gap:10px; flex-wrap:wrap; justify-content:flex-end; }
.metric-grid { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; }
.metric-card { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:14px; padding:16px; }
.metric-card.active { border-color:#409eff; background:#12223d; }
.metric-label { color:#909399; font-size:12px; }
.metric-value { margin-top:8px; color:#fff; font-size:28px; font-weight:900; }
.metric-sub { margin-top:6px; color:#7e8797; font-size:12px; }
.panel-card { border-radius:14px; }
.card-header { display:flex; justify-content:space-between; align-items:center; gap:12px; font-weight:800; }
.muted { color:#909399; font-size:12px; }
.evolution-config-form :deep(.el-form-item) { margin-bottom:14px; }
.config-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:4px 18px; }
.config-actions { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-top:8px; }
.field-hint { color:#909399; font-size:12px; line-height:1.5; margin-top:4px; width:100%; }
.auto-scan-status {
  display:flex;
  flex-direction:column;
  gap:8px;
  margin-top:12px;
  padding:12px;
  border:1px solid #2a2a4a;
  border-radius:12px;
  background:#111827;
}
.auto-scan-status > div:first-child { display:flex; align-items:center; gap:8px; }
.auto-scan-meta { display:flex; gap:12px; flex-wrap:wrap; color:#d7dce7; font-size:12px; }
.auto-scan-error { color:#f56c6c; font-size:12px; line-height:1.5; }
.horizon-list { display:flex; flex-direction:column; gap:16px; }
.horizon-item { background:#16162a; border:1px solid #2a2a4a; border-radius:12px; padding:14px; }
.horizon-title { display:flex; justify-content:space-between; color:#fff; font-weight:800; margin-bottom:10px; }
.horizon-meta { display:flex; justify-content:space-between; gap:8px; margin-top:8px; color:#909399; font-size:12px; }
.table-actions { display:flex; gap:8px; }
.stock-cell { display:flex; flex-direction:column; gap:2px; }
.stock-name { color:#fff; font-weight:800; }
.stock-code { color:#909399; font-size:12px; }
.prob { color:#7db7ff; font-weight:900; }
.compare-panel { display:flex; flex-direction:column; gap:14px; }
.compare-stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
.compare-stat { background:#16162a; border:1px solid #2a2a4a; border-radius:12px; padding:12px; display:flex; justify-content:space-between; align-items:center; }
.compare-stat span { color:#909399; font-size:12px; }
.compare-stat b { color:#fff; font-size:24px; }
.compare-stat.new { border-color:#409eff; }
.compare-stat.overlap { border-color:#f56c6c; }
.compare-stat.dropped { border-color:#67c23a; }
.compare-columns { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.compare-col { background:#111827; border:1px solid #2a2a4a; border-radius:12px; padding:12px; min-height:120px; }
.compare-title { color:#fff; font-weight:800; margin-bottom:10px; }
.compare-stock { display:flex; justify-content:space-between; align-items:center; gap:10px; padding:8px 0; border-bottom:1px solid #253046; }
.compare-stock:last-child { border-bottom:none; }
.compare-stock span { color:#d7dce7; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.compare-stock b { color:#7db7ff; font-family:monospace; }
.compare-stock.strong b { color:#f56c6c; }
.compare-stock.muted-stock { opacity:.72; }
.gate-tags { display:flex; flex-wrap:wrap; gap:6px; }
.wf-meta,
.wf-detail {
  display:flex;
  flex-direction:column;
  gap:2px;
  margin-top:6px;
  color:#909399;
  font-size:12px;
  line-height:1.4;
}
.decision-stack { display:flex; flex-direction:column; gap:6px; }
.decision-text { color:#d7dce7; font-size:12px; }

@media (max-width: 1100px) {
  .hero-card { flex-direction:column; }
  .hero-actions { justify-content:flex-start; }
  .metric-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .config-grid { grid-template-columns:1fr; }
  .compare-stats { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .compare-columns { grid-template-columns:1fr; }
}
</style>
