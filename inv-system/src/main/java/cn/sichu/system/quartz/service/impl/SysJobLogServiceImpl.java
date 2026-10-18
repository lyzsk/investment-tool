package cn.sichu.system.quartz.service.impl;

import cn.sichu.system.quartz.entity.SysJobLog;
import cn.sichu.system.quartz.mapper.SysJobLogMapper;
import cn.sichu.system.quartz.service.ISysJobLogService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import org.springframework.stereotype.Service;

/**
 * @author sichu huang
 * @since 2025/12/07 16:32
 */
@Service
public class SysJobLogServiceImpl extends ServiceImpl<SysJobLogMapper, SysJobLog>
    implements ISysJobLogService {
}
